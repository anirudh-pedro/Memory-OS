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
                    "chunk_text": chunk["chunk_text"],
                    "chunk_index": chunk["chunk_index"]
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

def run_semantic_search(query: str, limit: int = 5, source_filter: str = None, raw_scores: bool = False) -> list:
    embedder = Embedder()
    vector = embedder.embed_query(query)
    
    query_filter = None
    if source_filter:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="source_type",
                    match=models.MatchValue(value=source_filter)
                )
            ]
        )
        
    client = get_qdrant_client()
    try:
        # If we need raw scores, query with the exact limit.
        # Otherwise, query a larger limit (e.g. limit * 4) to allow for keyword boost re-ranking.
        qdrant_limit = limit if raw_scores else limit * 4
        
        search_result = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            query_filter=query_filter,
            limit=qdrant_limit
        )
        
        results = []
        for point in search_result.points:
            payload = point.payload
            item = {
                "repository_name": payload.get("repository_name"),
                "document_name": payload.get("document_name"),
                "source_type": payload.get("source_type"),
                "chunk_text": payload.get("chunk_text"),
                "chunk_index": payload.get("chunk_index")
            }
            
            if raw_scores:
                item["score"] = point.score
            else:
                boost = compute_keyword_boost(item, query)
                item["score"] = round((point.score * 0.8) + (boost * 0.2), 4)
                
            results.append(item)
            
        if not raw_scores:
            results.sort(key=lambda x: (-x["score"], x.get("repository_name") or ""))
            
        return results[:limit]
    except Exception:
        return []
    finally:
        client.close()

def compute_keyword_boost(item: dict, query: str) -> float:
    repo_name = item.get("repo_name") or ""
    file_name = item.get("file_name") or ""
    description = item.get("description") or ""
    
    if not description and repo_name:
        from storage.db import get_repository_details
        details = get_repository_details(repo_name)
        if details:
            description = details.get("description") or ""
            
    query_lower = query.lower().strip()
    stop_words = {"a", "an", "the", "in", "of", "and", "or", "to", "for", "with", "is", "at", "on", "by"}
    query_terms = [term for term in query_lower.split() if term not in stop_words and len(term) > 1]
    if not query_terms:
        query_terms = [term for term in query_lower.split() if len(term) > 0]
        
    repo_lower = repo_name.lower()
    desc_lower = description.lower()
    file_lower = file_name.lower()
    
    boost = 0.0
    
    # 1. Repository name contains query terms
    if any(term in repo_lower for term in query_terms):
        boost += 0.5
        # Exact match bonus
        if query_lower == repo_lower:
            boost += 0.3
            
    # 2. README title contains query terms (document is README.md and repo name contains query terms)
    if "readme" in file_lower and any(term in repo_lower for term in query_terms):
        boost += 0.2
        
    # 3. Repository description contains query terms
    if any(term in desc_lower for term in query_terms):
        boost += 0.2
        
    return min(1.0, boost)

def hybrid_search(query: str, source_filter: str = None) -> list:
    from storage.db import search_local_knowledge_ranked
    
    # 1. Run keyword search
    keyword_results = search_local_knowledge_ranked(query)
    
    # 2. Run semantic search
    semantic_results = run_semantic_search(query, limit=20, source_filter=source_filter)
    
    # Create candidate map to merge results
    candidates = {}
    
    # Parse keyword search results
    for item in keyword_results:
        t = item["type"]
        if t == "repository":
            key = f"repository:{item['repo_name'].lower()}"
            candidates[key] = {
                "type": "repository",
                "repo_name": item["repo_name"],
                "language": item.get("language"),
                "description": item.get("description"),
                "semantic_similarity": 0.0
            }
        elif t == "document":
            key = f"document:{item['repo_name'].lower()}:{item['file_name'].lower()}"
            candidates[key] = {
                "type": "document",
                "repo_name": item["repo_name"],
                "file_name": item["file_name"],
                "content": item["content"],
                "semantic_similarity": 0.0
            }
        elif t == "email":
            key = f"email:{item['subject'].lower()}"
            candidates[key] = {
                "type": "email",
                "subject": item["subject"],
                "sender": item["sender"],
                "snippet": item["snippet"],
                "semantic_similarity": 0.0
            }
            
    # Merge semantic search results (keep highest semantic score per unique result key)
    for sem in semantic_results:
        source = sem["source_type"]
        
        if source == "repository":
            key = f"repository:{sem['repository_name'].lower()}"
            if key not in candidates:
                candidates[key] = {
                    "type": "repository",
                    "repo_name": sem["repository_name"],
                    "description": sem["chunk_text"],
                    "semantic_similarity": sem["score"]
                }
            else:
                candidates[key]["semantic_similarity"] = max(candidates[key]["semantic_similarity"], sem["score"])
                
        elif source == "document":
            key = f"document:{sem['repository_name'].lower()}:{sem['document_name'].lower()}"
            if key not in candidates:
                candidates[key] = {
                    "type": "document",
                    "repo_name": sem["repository_name"],
                    "file_name": sem["document_name"],
                    "content": sem["chunk_text"],
                    "semantic_similarity": sem["score"]
                }
            else:
                candidates[key]["semantic_similarity"] = max(candidates[key]["semantic_similarity"], sem["score"])
                
        elif source == "email":
            key = f"email:{sem['document_name'].lower()}"
            if key not in candidates:
                candidates[key] = {
                    "type": "email",
                    "subject": sem["document_name"],
                    "sender": "Gmail Index",
                    "snippet": sem["chunk_text"],
                    "semantic_similarity": sem["score"]
                }
            else:
                candidates[key]["semantic_similarity"] = max(candidates[key]["semantic_similarity"], sem["score"])
                
    # Filter candidates by source_filter if specified
    filtered_candidates = []
    for cand in candidates.values():
        t = cand["type"]
        if source_filter:
            # Match the source_filter exactly
            if source_filter == "repository" and t != "repository":
                continue
            if source_filter == "document" and t != "document":
                continue
            if source_filter == "email" and t != "email":
                continue
        filtered_candidates.append(cand)
        
    # Calculate final scores
    results = []
    for cand in filtered_candidates:
        sim = cand["semantic_similarity"]
        boost = compute_keyword_boost(cand, query)
        final_score = round((sim * 0.8) + (boost * 0.2), 4)
        
        cand["score"] = final_score
        results.append(cand)
        
    # Re-sort ranked results
    results.sort(key=lambda x: (-x["score"], x.get("repo_name") or x.get("subject") or ""))
    return results
