import os
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from core.embedder import Embedder
from core.chunker import generate_and_save_chunks
from storage.db import (
    get_all_document_chunks,
    get_document_chunk_count,
    get_repository_document_count
)

COLLECTION_NAME = "memory_os"

def get_qdrant_client() -> QdrantClient:
    return QdrantClient(path="qdrant_storage")

def init_qdrant_collection(client: QdrantClient, force_recreate: bool = False):
    exists = False
    try:
        collection_info = client.get_collection(COLLECTION_NAME)
        exists = True
        
        config = collection_info.config.params.vectors
        if isinstance(config, dict):
            dim = config.get("size")
        else:
            dim = getattr(config, "size", None)
            
        if dim != 384 or force_recreate:
            client.delete_collection(COLLECTION_NAME)
            exists = False
    except (UnexpectedResponse, ValueError, Exception):
        exists = False
        
    if not exists:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=384,
                distance=models.Distance.COSINE
            )
        )

def upload_chunks_to_qdrant(client: QdrantClient, chunks: list, embeddings: list):
    points = []
    for idx, (chunk, vector) in enumerate(zip(chunks, embeddings)):
        points.append(
            models.PointStruct(
                id=chunk["id"],
                vector=vector,
                payload={
                    "chunk_id": chunk["id"],
                    "repository_name": chunk["repository_name"],
                    "document_name": chunk["document_name"],
                    "source_type": chunk["source_type"],
                    "chunk_text": chunk["chunk_text"]
                }
            )
        )
    
    if points:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )

def run_reindexing():
    # 1. Generate and save SQLite chunks
    generate_and_save_chunks()
    
    # 2. Load chunks
    chunks = get_all_document_chunks()
    if not chunks:
        # Return empty summary if no content
        return {
            "documents": get_repository_document_count(),
            "chunks": 0,
            "collection": COLLECTION_NAME,
            "dimension": 384,
            "vectors_uploaded": 0
        }
    
    # 3. Generate embeddings
    embedder = Embedder()
    texts = [c["chunk_text"] for c in chunks]
    embeddings = embedder.embed_documents(texts)
    
    # 4. Recreate collection and upload
    client = get_qdrant_client()
    try:
        init_qdrant_collection(client, force_recreate=True)
        upload_chunks_to_qdrant(client, chunks, embeddings)
    finally:
        client.close()
        
    return {
        "documents": get_repository_document_count(),
        "chunks": len(chunks),
        "collection": COLLECTION_NAME,
        "dimension": 384,
        "vectors_uploaded": len(chunks)
    }

def get_vector_index_stats() -> dict:
    client = get_qdrant_client()
    try:
        collection_info = client.get_collection(COLLECTION_NAME)
        config = collection_info.config.params.vectors
        if isinstance(config, dict):
            dim = config.get("size")
        else:
            dim = getattr(config, "size", None)
            
        vectors_count = getattr(collection_info, "points_count", 0)
        return {
            "collection": COLLECTION_NAME,
            "dimension": dim,
            "vectors": vectors_count,
            "embedding_model": "all-MiniLM-L6-v2",
            "exists": True
        }
    except Exception:
        return {
            "collection": COLLECTION_NAME,
            "dimension": 384,
            "vectors": 0,
            "embedding_model": "all-MiniLM-L6-v2",
            "exists": False
        }
    finally:
        client.close()

def run_semantic_search(query: str, limit: int = 5) -> list:
    embedder = Embedder()
    vector = embedder.embed_query(query)
    
    client = get_qdrant_client()
    try:
        search_result = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit
        )
        
        results = []
        for point in search_result.points:
            payload = point.payload
            results.append({
                "score": point.score,
                "repository_name": payload.get("repository_name"),
                "document_name": payload.get("document_name"),
                "source_type": payload.get("source_type"),
                "chunk_text": payload.get("chunk_text")
            })
        return results
    except Exception:
        return []
    finally:
        client.close()

def hybrid_search(query: str) -> list:
    from storage.db import search_local_knowledge_ranked
    
    # 1. Run keyword search
    keyword_results = search_local_knowledge_ranked(query)
    
    # 2. Run semantic search
    semantic_results = run_semantic_search(query, limit=10)
    
    # Create lookup map
    lookup = {}
    for idx, item in enumerate(keyword_results):
        t = item["type"]
        if t == "repository":
            key = f"repository:{item['repo_name'].lower()}"
        elif t == "document":
            key = f"document:{item['repo_name'].lower()}:{item['file_name'].lower()}"
        elif t == "email":
            key = f"email:{item['subject'].lower()}"
        lookup[key] = idx
        
    # We want to apply semantic score boost ONLY ONCE per unique document/email.
    # Track which keys have already received a semantic boost.
    boosted_keys = set()
    
    # Merge results
    for sem in semantic_results:
        sem_score_points = round(sem["score"] * 10, 2)
        source = sem["source_type"]
        
        if source == "github":
            doc_key = f"document:{sem['repository_name'].lower()}:{sem['document_name'].lower()}"
            if doc_key in boosted_keys:
                continue
            boosted_keys.add(doc_key)
            
            if doc_key in lookup:
                keyword_results[lookup[doc_key]]["score"] += sem_score_points
            else:
                keyword_results.append({
                    "type": "document",
                    "score": sem_score_points,
                    "repo_name": sem["repository_name"],
                    "file_name": sem["document_name"],
                    "content": sem["chunk_text"]
                })
                lookup[doc_key] = len(keyword_results) - 1
        elif source == "gmail":
            email_key = f"email:{sem['document_name'].lower()}"
            if email_key in boosted_keys:
                continue
            boosted_keys.add(email_key)
            
            if email_key in lookup:
                keyword_results[lookup[email_key]]["score"] += sem_score_points
            else:
                keyword_results.append({
                    "type": "email",
                    "score": sem_score_points,
                    "subject": sem["document_name"],
                    "sender": "Gmail Index",
                    "snippet": sem["chunk_text"]
                })
                lookup[email_key] = len(keyword_results) - 1
                
    # Re-sort ranked results
    keyword_results.sort(key=lambda x: (-x["score"], x.get("repo_name") or x.get("subject") or ""))
    return keyword_results
