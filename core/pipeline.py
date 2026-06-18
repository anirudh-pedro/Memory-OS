import logging
import json
from datetime import datetime
from typing import List, Dict, Any
from core.models import Memory, MemoryChunk
from core.db import DatabaseConnectionManager
from core.embeddings import LocalTFIDFEmbedder
from core.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

class IngestionPipeline:
    def __init__(self, db_manager: DatabaseConnectionManager, vector_store: QdrantVectorStore, embedder: LocalTFIDFEmbedder, graph_store=None):
        self.db_manager = db_manager
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store

    def chunk_text(self, text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
        """Split text into overlapping chunks of rough size."""
        if not text:
            return []
            
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # If paragraph itself is too large, split it by characters
                if len(para) > chunk_size:
                    start = 0
                    while start < len(para):
                        end = start + chunk_size
                        chunks.append(para[start:end])
                        start += chunk_size - overlap
                    current_chunk = ""
                else:
                    current_chunk = para
                    
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def upsert_memory_to_db(self, memory: Memory) -> int:
        """Saves memory to SQLite workspace_cache table and returns the rowid."""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO workspace_cache (source_app, external_id, title, content, metadata_json, last_synced)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_app, external_id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    last_synced = excluded.last_synced
                RETURNING id
                """,
                (
                    memory.source_app,
                    memory.external_id,
                    memory.title,
                    memory.content,
                    json.dumps(memory.metadata_json),
                    memory.last_synced.isoformat()
                )
            )
            row = cursor.fetchone()
            if row:
                row_id = row[0]
            else:
                # Fallback if RETURNING is not supported or returning empty
                cursor.execute(
                    "SELECT id FROM workspace_cache WHERE source_app = ? AND external_id = ?",
                    (memory.source_app, memory.external_id)
                )
                row_id = cursor.fetchone()[0]
            conn.commit()
            return row_id
        except Exception as e:
            logger.error(f"Failed to upsert memory {memory.title} to database: {e}")
            raise e
        finally:
            conn.close()

    def run_ingestion(self, memories: List[Memory]) -> int:
        """Run standard pipeline for a list of normalized Memory objects:
        1. Save to SQLite database
        2. Chunk text content
        3. Embed and upsert chunks into Qdrant vector store
        Returns the number of memories ingested.
        """
        if not memories:
            logger.info("No memories provided for ingestion.")
            return 0

        logger.info(f"Starting pipeline ingestion for {len(memories)} memories...")
        
        # 1. Update vocabulary by fetching all existing cached text to fit embedder
        all_docs = []
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT title, content FROM workspace_cache")
        for row in cursor.fetchall():
            all_docs.append(f"{row['title']} {row['content']}")
        conn.close()

        # Add the incoming memories to the document list to ensure vocabulary covers them
        for mem in memories:
            all_docs.append(f"{mem.title} {mem.content}")

        logger.info(f"Fitting TF-IDF embedder on combined database corpus of {len(all_docs)} documents...")
        self.embedder.fit(all_docs)
        
        vocab_size = len(self.embedder.vocabulary)
        dimension = vocab_size if vocab_size > 0 else 1
        
        # Initialize vector collection to match updated vocabulary dimension
        self.vector_store.initialize_collection(dimension=dimension)

        # 2. Ingest and index memories
        ingested_count = 0
        all_chunks = []
        
        for memory in memories:
            try:
                # Step A: Save/Update in SQLite DB
                memory_id = self.upsert_memory_to_db(memory)
                
                # Step B: Segment content into chunks
                text_chunks = self.chunk_text(memory.content)
                if not text_chunks:
                    # Fallback to indexing title if content is empty
                    text_chunks = [memory.title]

                # Step C: Prepare chunks and embed them
                vectors = self.embedder.embed_documents(text_chunks)
                for i, text in enumerate(text_chunks):
                    all_chunks.append(
                        MemoryChunk(
                            chunk_id=f"wc_{memory_id}_{i}",
                            memory_id=memory_id,
                            text=text,
                            vector=vectors[i],
                            metadata={
                                "source_app": memory.source_app,
                                "external_id": memory.external_id,
                                "type": "workspace_cache",
                                "title": memory.title
                            }
                        )
                    )
                ingested_count += 1
            except Exception as e:
                logger.error(f"Failed to ingest memory '{memory.title}': {e}")

        # Step D: Bulk upsert to Qdrant vector store
        if all_chunks:
            logger.info(f"Upserting {len(all_chunks)} semantic chunks to Qdrant vector store...")
            self.vector_store.upsert_chunks(all_chunks)

        # Step E: Trigger memory consolidation & project auto-detection
        if self.graph_store:
            try:
                from memory.quality import MemoryQualityPipeline
                logger.info("Executing MemoryQualityPipeline service checks...")
                pipeline = MemoryQualityPipeline(self.db_manager, self.graph_store)
                pipeline.run_full_consolidation()
            except Exception as ex:
                logger.error(f"Failed to run memory consolidations: {ex}")

        logger.info(f"Ingestion pipeline run completed. Successfully processed {ingested_count} memories.")
        return ingested_count
