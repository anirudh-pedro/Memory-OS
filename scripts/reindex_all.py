import sys
import os
import json
import logging
from datetime import datetime

# Adjust Python path to load modules from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import DatabaseConnectionManager
from core.embeddings import LocalTFIDFEmbedder
from core.vector_store import QdrantVectorStore
from core.models import MemoryChunk

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("reindex_script")

def run_migration_and_reindex(vector_store=None):
    db_path = "memory.db"
    db_manager = DatabaseConnectionManager(db_path=db_path)
    
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    
    logger.info("Reading workspace cache entries...")
    cursor.execute("SELECT id, source_app, external_id, title, content FROM workspace_cache")
    cache_rows = cursor.fetchall()
    
    logger.info("Reading entities...")
    cursor.execute("SELECT name, entity_type, description, properties_json FROM entities")
    entity_rows = cursor.fetchall()
    conn.close()

    documents = []
    chunk_mapping = []

    # Process workspace cache rows
    for row in cache_rows:
        title = row["title"] or ""
        content = row["content"] or ""
        text = f"{title} {content}"
        documents.append(text)
        chunk_mapping.append({
            "memory_id": row["id"],
            "chunk_id": f"wc_{row['id']}",
            "text": text,
            "metadata": {
                "source_app": row["source_app"],
                "external_id": row["external_id"],
                "type": "workspace_cache",
                "title": title
            }
        })

    # Process graph entities
    for i, row in enumerate(entity_rows):
        name = row["name"] or ""
        entity_type = row["entity_type"] or ""
        desc = row["description"] or ""
        props = row["properties_json"] or "{}"
        text = f"{name} {entity_type} {desc} {props}"
        documents.append(text)
        chunk_mapping.append({
            "memory_id": -1,  # Entities don't have a direct workspace_cache memory_id
            "chunk_id": f"ent_{i}_{name}",
            "text": text,
            "metadata": {
                "name": name,
                "entity_type": entity_type,
                "type": "graph_node",
                "description": desc
            }
        })

    if not documents:
        logger.info("No documents found to index.")
        return

    logger.info(f"Fitting TF-IDF embedder on {len(documents)} documents...")
    embedder = LocalTFIDFEmbedder()
    embedder.fit(documents)
    
    dimension = len(embedder.vocabulary)
    if dimension == 0:
        dimension = 1

    logger.info(f"Initializing Qdrant collection with dimension: {dimension}")
    if vector_store is None:
        vector_store = QdrantVectorStore()
    vector_store.initialize_collection(dimension=dimension, force_recreate=True)
    
    logger.info("Computing embeddings and preparing chunks...")
    vectors = embedder.embed_documents(documents)
    
    chunks = []
    for i, item in enumerate(chunk_mapping):
        chunks.append(
            MemoryChunk(
                chunk_id=item["chunk_id"],
                memory_id=item["memory_id"],
                text=item["text"],
                vector=vectors[i],
                metadata=item["metadata"]
            )
        )
        
    logger.info("Uploading vectors to Qdrant store...")
    success = vector_store.upsert_chunks(chunks)
    if success:
        logger.info("Migration & indexing completed successfully!")
    else:
        logger.error("Migration finished but failed to upsert vectors to Qdrant.")

if __name__ == "__main__":
    run_migration_and_reindex()
