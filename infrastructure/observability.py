"""
Infrastructure: Observability and Performance Monitoring.

Parses logs from the active log file (or tracks metrics) to measure:
- Sync execution time
- Embedding generation latency
- Qdrant upload time
- Neo4j insertion time
- LLM call count and durations
- RAG query execution time
"""

import re
from pathlib import Path
from infrastructure.workspace import get_workspace_root


def get_log_file_path() -> Path:
    """Return path to active memory_os.log."""
    return get_workspace_root() / "logs" / "memory_os.log"


def parse_observability_metrics() -> dict:
    """Scan the memory_os.log file and parse latency/observability metrics."""
    log_path = get_log_file_path()
    
    # Fallback to local logs directory if not in home workspace yet
    if not log_path.exists():
        log_path = Path("logs/memory_os.log")
        
    metrics = {
        "sync_times": [],
        "embedding_times": [],  # (duration, num_chunks)
        "qdrant_uploads": [],   # (duration, num_vectors)
        "neo4j_inserts": [],    # (duration, nodes, relationships)
        "llm_calls": [],
        "retrievals": [],
        "rag_times": [],
    }
    
    if not log_path.exists():
        return metrics

    # Regex definitions matching existing logs in core/storage/main
    r_sync = re.compile(r"Sync completed in (\d+\.\d+)s")
    r_rebuild = re.compile(r"Full rebuild completed in (\d+\.\d+)s")
    r_embed = re.compile(r"Embedding generation complete for (\d+) chunks in (\d+\.\d+)s")
    r_upload = re.compile(r"Vector upload complete for (\d+) vectors in (\d+\.\d+)s")
    r_graph = re.compile(r"Graph Sync Complete.*Nodes: (\d+), Relationships: (\d+)\. Duration: (\d+\.\d+)s")
    r_llm = re.compile(r"Groq LLM generation finished in (\d+\.\d+)s")
    r_retrieval = re.compile(r"Hybrid retrieval finished for query:.*Retrieved (\d+) items in (\d+\.\d+)s")
    r_rag = re.compile(r"RAG pipeline complete for question:.*in (\d+\.\d+)s")

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                # Sync
                m = r_sync.search(line) or r_rebuild.search(line)
                if m:
                    metrics["sync_times"].append(float(m.group(1)))
                    continue
                
                # Embeddings
                m = r_embed.search(line)
                if m:
                    metrics["embedding_times"].append((float(m.group(2)), int(m.group(1))))
                    continue
                
                # Qdrant Uploads
                m = r_upload.search(line)
                if m:
                    metrics["qdrant_uploads"].append((float(m.group(2)), int(m.group(1))))
                    continue
                
                # Neo4j Graph Sync
                m = r_graph.search(line)
                if m:
                    metrics["neo4j_inserts"].append((float(m.group(3)), int(m.group(1)), int(m.group(2))))
                    continue
                
                # LLM Calls
                m = r_llm.search(line)
                if m:
                    metrics["llm_calls"].append(float(m.group(1)))
                    continue
                
                # Hybrid Retrieval
                m = r_retrieval.search(line)
                if m:
                    metrics["retrievals"].append(float(m.group(2)))
                    continue
                
                # RAG Times
                m = r_rag.search(line)
                if m:
                    metrics["rag_times"].append(float(m.group(1)))
                    continue
    except Exception:
        pass
        
    return metrics


def get_performance_summary() -> dict:
    """Format metrics into a user-friendly statistics summary."""
    data = parse_observability_metrics()
    
    def avg(lst):
        return sum(lst) / len(lst) if lst else 0.0

    # Sync
    syncs = data["sync_times"]
    last_sync = syncs[-1] if syncs else 0.0
    avg_sync = avg(syncs)

    # Embeddings
    embeds = data["embedding_times"]
    total_embed_time = sum(t for t, _ in embeds)
    total_chunks = sum(c for _, c in embeds)
    avg_chunk_latency = (total_embed_time / total_chunks) if total_chunks > 0 else 0.0

    # Qdrant uploads
    uploads = data["qdrant_uploads"]
    total_upload_time = sum(t for t, _ in uploads)
    total_vectors = sum(v for _, v in uploads)
    avg_vector_latency = (total_upload_time / total_vectors) if total_vectors > 0 else 0.0

    # Neo4j
    inserts = data["neo4j_inserts"]
    avg_neo4j = avg([t for t, _, _ in inserts])
    total_nodes = sum(n for _, n, _ in inserts)
    total_rels = sum(r for _, _, r in inserts)

    # LLM
    llms = data["llm_calls"]
    total_llm_calls = len(llms)
    avg_llm = avg(llms)

    # Retrieval & RAG
    retrievals = data["retrievals"]
    avg_retrieval = avg(retrievals)
    
    rags = data["rag_times"]
    avg_rag = avg(rags)

    return {
        "sync_count": len(syncs),
        "last_sync_duration": last_sync,
        "avg_sync_duration": avg_sync,
        "avg_chunk_latency": avg_chunk_latency,
        "avg_vector_latency": avg_vector_latency,
        "avg_neo4j_sync": avg_neo4j,
        "total_nodes_synced": total_nodes,
        "total_rels_synced": total_rels,
        "llm_call_count": total_llm_calls,
        "avg_llm_duration": avg_llm,
        "avg_retrieval_duration": avg_retrieval,
        "avg_rag_duration": avg_rag,
    }
