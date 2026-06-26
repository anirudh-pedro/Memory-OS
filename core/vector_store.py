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

_qdrant_client = None

def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(path="qdrant_storage")
    return _qdrant_client

def close_qdrant_client():
    global _qdrant_client
    if _qdrant_client is not None:
        try:
            _qdrant_client.close()
        except Exception:
            pass
        _qdrant_client = None

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
        # Upload in batches of 100 for stability
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=batch
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
    init_qdrant_collection(client, force_recreate=True)
    upload_chunks_to_qdrant(client, chunks, embeddings)
        
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

def get_vector_chunks(repo_name: str, limit: int = 5) -> list:
    """Retrieve the first `limit` chunks for a given repository from Qdrant.
    Returns a list of Record objects.
    """
    client = get_qdrant_client()
    try:
        filter_expr = models.Filter(
            must=[
                models.FieldCondition(
                    key="repository_name",
                    match=models.MatchValue(value=repo_name)
                )
            ]
        )
        points, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=filter_expr,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        return points
    except Exception as e:
        import logging
        logging.getLogger("vector_store").error(f"Error fetching vector chunks: {e}")
        return []

def count_vector_chunks(repo_name: str) -> int:
    """Count the total number of vectors for a given repository in Qdrant."""
    client = get_qdrant_client()
    try:
        filter_expr = models.Filter(
            must=[
                models.FieldCondition(
                    key="repository_name",
                    match=models.MatchValue(value=repo_name)
                )
            ]
        )
        result = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=filter_expr,
            exact=True
        )
        return result.count
    except Exception as e:
        import logging
        logging.getLogger("vector_store").error(f"Error counting vector chunks: {e}")
        return 0

def run_semantic_search(query: str, limit: int = 5, source_filter: str = None, raw_scores: bool = False, repo_filter: str = None) -> list:
    embedder = Embedder()
    vector = embedder.embed_query(query)
    
    must_conditions = []
    if source_filter:
        must_conditions.append(
            models.FieldCondition(
                key="source_type",
                match=models.MatchValue(value=source_filter)
            )
        )
    if repo_filter:
        must_conditions.append(
            models.FieldCondition(
                key="repository_name",
                match=models.MatchValue(value=repo_filter)
            )
        )
        
    query_filter = models.Filter(
        must=must_conditions,
        must_not=[
            models.FieldCondition(
                key="source_type",
                match=models.MatchValue(value="repository_metadata")
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
        
        query_lower = query.lower()
        tech_keywords = ["python", "javascript", "typescript", "react", "node", "express", "mongo", "fastapi", "postgres", "tailwind", "docker", "kafka", "redis", "plotly", "gemini", "groq", "next.js", "firebase", "sqlite", "repo", "repository", "code", "github", "project", "readme"]
        is_repo_focused = any(k in query_lower for k in tech_keywords)

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
                score = round((point.score * 0.8) + (boost * 0.2), 4)
                # Down-weight emails for repository-focused queries
                if is_repo_focused and item["source_type"] == "email":
                    score = round(score * 0.1, 4)
                item["score"] = score
                
            results.append(item)
            
        if not raw_scores:
            results.sort(key=lambda x: (-x["score"], x.get("repository_name") or ""))
            
        return results[:limit]
    except Exception:
        return []

def compute_keyword_boost(item: dict, query: str) -> float:
    repo_name = item.get("repo_name") or item.get("repository_name") or ""
    file_name = item.get("file_name") or item.get("document_name") or ""
    source_type = item.get("source_type") or item.get("type") or ""
    description = item.get("description") or item.get("chunk_text") or item.get("content") or item.get("snippet") or ""
    
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
    if repo_lower and any(term in repo_lower for term in query_terms):
        boost += 0.4
        # Exact match bonus
        if query_lower == repo_lower:
            boost += 0.2
            
    # 2. README title priority boost
    if "readme" in file_lower:
        boost += 0.3
        if any(term in repo_lower or term in file_lower for term in query_terms):
            boost += 0.1
        
    # 3. Repository description contains query terms
    if desc_lower and any(term in desc_lower for term in query_terms):
        boost += 0.1
        
    # 4. Document source type boost
    if source_type == "document":
        boost += 0.1
        
    return min(1.0, boost)

def detect_repo_in_query(query: str) -> str:
    """Check if any known repository name is mentioned in the query.
    Returns the exact case-sensitive repository name if found, else None.
    """
    import re
    from storage.db import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT repo_name FROM repository_documents WHERE repo_name IS NOT NULL")
    names = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    query_lower = query.lower()
    # Sort by length descending to match longer names first (e.g. 'nextjs-ai-chatbot' before 'chatbot')
    for name in sorted(names, key=len, reverse=True):
        name_lower = name.lower()
        # Match word boundaries or replaced hyphens
        patterns = [
            r'\b' + re.escape(name_lower) + r'\b',
            r'\b' + re.escape(name_lower.replace('-', ' ')) + r'\b',
            r'\b' + re.escape(name_lower.replace('-', '')) + r'\b',
        ]
        if any(re.search(pat, query_lower) for pat in patterns):
            return name
    return None

def hybrid_search(query: str, source_filter: str = None, repo_filter: str = None) -> list:
    from storage.db import search_local_knowledge_ranked
    
    if not repo_filter:
        repo_filter = detect_repo_in_query(query)
    
    # 1. Run keyword search
    keyword_results = search_local_knowledge_ranked(query, repo_filter=repo_filter)
    
    # 2. Run semantic search
    semantic_results = run_semantic_search(query, limit=20, source_filter=source_filter, raw_scores=True, repo_filter=repo_filter)
    
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
        
    query_lower = query.lower()
    stop_words = {"a", "an", "the", "in", "of", "and", "or", "to", "for", "with", "is", "at", "on", "by", "what", "which", "does", "use", "how", "tell", "me", "about"}
    query_terms = [t for t in query_lower.split() if t not in stop_words and len(t) > 1]
    if not query_terms:
        query_terms = [t for t in query_lower.split() if len(t) > 0]
        
    tech_keywords = ["python", "javascript", "typescript", "react", "node", "express", "mongo", "fastapi", "postgres", "tailwind", "docker", "kafka", "redis", "plotly", "gemini", "groq", "next.js", "firebase", "sqlite", "repo", "repository", "code", "github", "project", "readme"]
    is_repo_focused = any(k in query_lower for k in tech_keywords)
 
    # Calculate final scores using the new hybrid ranking formula
    results = []
    for cand in filtered_candidates:
        sim = cand["semantic_similarity"]
        
        # 1. repository_match (score = 1.0 if the query matches this candidate's repository name)
        repo_name = cand.get("repo_name") or ""
        repo_match_val = 0.0
        if repo_filter and repo_name.lower() == repo_filter.lower():
            repo_match_val = 1.0
            
        # 2. readme_bonus (score = 1.0 if document name contains "readme")
        file_name = cand.get("file_name") or ""
        readme_bonus_val = 1.0 if "readme" in file_name.lower() else 0.0
        
        # 3. keyword_match (score = 1.0 if any query term is found in content)
        text_to_search = ""
        if cand["type"] == "repository":
            text_to_search = f"{cand.get('repo_name') or ''} {cand.get('description') or ''}"
        elif cand["type"] == "document":
            text_to_search = f"{cand.get('file_name') or ''} {cand.get('content') or ''}"
        elif cand["type"] == "email":
            text_to_search = f"{cand.get('subject') or ''} {cand.get('snippet') or ''}"
            
        text_to_search_lower = text_to_search.lower()
        keyword_match_val = 1.0 if any(term in text_to_search_lower for term in query_terms) else 0.0
        
        # Calculate final hybrid score
        final_score = round(
            (0.65 * sim) + 
            (0.20 * repo_match_val) + 
            (0.10 * readme_bonus_val) + 
            (0.05 * keyword_match_val),
            4
        )
        
        # Down-weight emails for repository-focused queries
        if is_repo_focused and cand["type"] == "email":
            final_score = round(final_score * 0.1, 4)
            
        cand["score"] = final_score
        results.append(cand)
        
    # Re-sort ranked results
    results.sort(key=lambda x: (-x["score"], x.get("repo_name") or x.get("subject") or ""))
    return results
