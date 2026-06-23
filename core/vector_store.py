from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from typing import List, Dict, Any, Optional
import logging
from core.models import MemoryChunk

logger = logging.getLogger(__name__)

class QdrantVectorStore:
    def __init__(self, path: Optional[str] = "qdrant_storage", collection_name: str = "memory_os"):
        self.path = path
        self.collection_name = collection_name
        self.is_persistent = False
        self.vector_retrieval_enabled = True
        
        if path:
            try:
                self.client = QdrantClient(path=path)
                self.is_persistent = True
            except Exception as e:
                logger.warning(
                    f"Storage folder '{path}' is already locked or inaccessible: {e}. "
                    "Falling back to in-memory Qdrant instance for this session."
                )
                self.client = QdrantClient(location=":memory:")
                self.path = None
        else:
            self.client = QdrantClient(location=":memory:")

    def collection_exists(self) -> bool:
        try:
            return self.client.collection_exists(self.collection_name)
        except Exception as e:
            logger.warning(f"Error checking collection existence: {e}")
            return False

    def save_metadata(self, embedder_type: str, dimension: int, version: str):
        import os
        import json
        metadata = {
            "embedder_type": embedder_type,
            "dimension": dimension,
            "version": version
        }
        meta_dir = self.path if self.path else "qdrant_storage"
        try:
            os.makedirs(meta_dir, exist_ok=True)
            meta_path = os.path.join(meta_dir, f"{self.collection_name}_metadata.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"Saved Qdrant collection metadata to {meta_path}: {metadata}")
        except Exception as e:
            logger.error(f"Failed to save collection metadata: {e}")

    def load_metadata(self) -> Optional[dict]:
        import os
        import json
        meta_dir = self.path if self.path else "qdrant_storage"
        meta_path = os.path.join(meta_dir, f"{self.collection_name}_metadata.json")
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load collection metadata from {meta_path}: {e}")
            return None

    def initialize_collection(self, dimension: int, force_recreate: bool = False, embedder: Optional[Any] = None):
        """Creates the collection if missing, or recreates it if force_recreate or vector dimension changed."""
        try:
            exists = self.collection_exists()
            mismatch_detected = False
            
            if exists:
                try:
                    info = self.client.get_collection(self.collection_name)
                    current_dim = info.config.params.vectors.size
                    if current_dim != dimension:
                        mismatch_detected = True
                        logger.info(f"Qdrant collection '{self.collection_name}' dimension mismatch (current: {current_dim}, target: {dimension}).")
                except Exception as ex:
                    logger.warning(f"Could not retrieve collection info: {ex}")
                    mismatch_detected = True

            if force_recreate or mismatch_detected:
                logger.info(f"Recreating Qdrant collection '{self.collection_name}' (force={force_recreate}, mismatch={mismatch_detected})...")
                if exists:
                    try:
                        self.client.delete_collection(self.collection_name)
                    except Exception as e:
                        logger.warning(f"Error deleting collection: {e}")
                
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
                )
                logger.info(f"Initialized Qdrant collection '{self.collection_name}' with dimension {dimension}.")
                self._save_inferred_metadata(dimension, embedder)
                
                if mismatch_detected and not force_recreate:
                    logger.info("Automatically triggering database-wide reindexing to align all vector dimensions...")
                    from scripts.reindex_all import run_migration_and_reindex
                    run_migration_and_reindex(vector_store=self)
            elif not exists:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
                )
                logger.info(f"Initialized Qdrant collection '{self.collection_name}' with dimension {dimension}.")
                self._save_inferred_metadata(dimension, embedder)
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant collection: {e}")
            raise e

    def _save_inferred_metadata(self, dimension: int, embedder: Optional[Any] = None):
        import os
        embedder_type = os.getenv("EMBEDDER_TYPE", "tfidf").lower()
        if embedder:
            embedder_type = embedder.__class__.__name__
            version = getattr(embedder, "version", f"{embedder_type}_{dimension}")
        else:
            version = f"{embedder_type}_{dimension}"
        self.save_metadata(embedder_type, dimension, version)

    def upsert_chunks(self, chunks: List[MemoryChunk]) -> bool:
        """Upserts a list of MemoryChunk objects containing pre-computed vectors."""
        if not chunks:
            return True
        try:
            points = []
            for i, chunk in enumerate(chunks):
                if not chunk.vector:
                    logger.warning(f"Skipping chunk {chunk.chunk_id} since it has no vector.")
                    continue
                points.append(
                    PointStruct(
                        id=hash(chunk.chunk_id) % (10**8),  # Unique integer ID
                        vector=chunk.vector,
                        payload={
                            "chunk_id": chunk.chunk_id,
                            "memory_id": chunk.memory_id,
                            "text": chunk.text,
                            **chunk.metadata
                        }
                    )
                )
            if points:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points
                )
                logger.info(f"Upserted {len(points)} points to Qdrant collection '{self.collection_name}'.")
                return True
        except Exception as e:
            logger.error(f"Failed to upsert chunks to Qdrant: {e}")
            return False
        return False

    def search(self, query_vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """Queries Qdrant vector store and returns list of hits with payloads and scores."""
        if not self.collection_exists():
            logger.warning(f"Qdrant collection '{self.collection_name}' does not exist.")
            return []
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit
            )
            results = []
            for hit in response.points:
                results.append({
                    "score": hit.score,
                    "payload": hit.payload
                })
            return results
        except Exception as e:
            logger.error(f"Vector search query failed: {e}")
            return []

    def delete_before(self, date_str: str) -> bool:
        """Deletes points from Qdrant that were synced before the specified ISO date string."""
        if not self.collection_exists():
            return False
        try:
            from qdrant_client.models import Filter, FieldCondition, Range
            qdrant_filter = Filter(must=[FieldCondition(key="last_synced", range=Range(lt=date_str))])
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qdrant_filter
            )
            logger.info(f"Deleted points synced before {date_str} from Qdrant.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete points from Qdrant: {e}")
            return False

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception as e:
                logger.warning(f"Error closing Qdrant client: {e}")
