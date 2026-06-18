from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from typing import List, Dict, Any, Optional
import logging
from core.models import MemoryChunk

logger = logging.getLogger(__name__)

class QdrantVectorStore:
    def __init__(self, path: Optional[str] = "qdrant_storage", collection_name: str = "memory_os"):
        if path:
            self.client = QdrantClient(path=path)
        else:
            self.client = QdrantClient(location=":memory:")
        self.collection_name = collection_name

    def collection_exists(self) -> bool:
        try:
            return self.client.collection_exists(self.collection_name)
        except Exception as e:
            logger.warning(f"Error checking collection existence: {e}")
            return False

    def initialize_collection(self, dimension: int, force_recreate: bool = False):
        """Creates the collection if missing, or recreates it if force_recreate or vector dimension changed."""
        try:
            exists = self.collection_exists()
            if exists and not force_recreate:
                info = self.client.get_collection(self.collection_name)
                current_dim = info.config.params.vectors.size
                if current_dim == dimension:
                    logger.info(f"Qdrant collection '{self.collection_name}' already exists with correct dimension {dimension}. Loading...")
                    return
                else:
                    logger.info(f"Qdrant collection '{self.collection_name}' dimension mismatch (current: {current_dim}, target: {dimension}). Recreating...")
                    self.client.delete_collection(self.collection_name)
            elif exists and force_recreate:
                logger.info(f"Force recreating Qdrant collection '{self.collection_name}'...")
                self.client.delete_collection(self.collection_name)
            
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
            )
            logger.info(f"Initialized Qdrant collection '{self.collection_name}' with dimension {dimension}.")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant collection: {e}")
            raise e

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
