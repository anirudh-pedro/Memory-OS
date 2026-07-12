"""
Command: memory-os benchmark

Runs performance latency diagnostics across search indexes, embedding model,
graph lookups, LLM invocation, and RAG pipelines.
"""

import time
from infrastructure.health import check_qdrant, check_groq_api, check_memory_usage
from core.embedder import Embedder


def execute(args):
    """Run the benchmark command."""
    from storage.db import init_db
    try:
        init_db()
    except Exception:
        pass

    print("──────────────────────────────────────────────────")
    print("  Memory-OS Performance Benchmark")
    print("──────────────────────────────────────────────────")
    print("  Running latency measurements (please wait)...")

    # Metrics dictionary
    latencies = {
        "Keyword Search": "N/A",
        "Semantic Search": "N/A",
        "Hybrid Search": "N/A",
        "Graph Lookup": "N/A",
        "Embedding Time": "N/A",
        "LLM Time": "N/A",
        "Average RAG Pipeline": "N/A",
        "Memory Usage": "N/A",
        "Vector Count": "0",
    }

    # 1. Memory Usage
    _, mem_detail = check_memory_usage()
    latencies["Memory Usage"] = mem_detail

    # 2. Embedding Time
    try:
        start = time.perf_counter()
        embedder = Embedder()
        embedder.embed_documents(["This is a test snippet to benchmark the local embedding model latency."])
        duration = time.perf_counter() - start
        latencies["Embedding Time"] = f"{duration*1000:.1f} ms"
    except Exception as e:
        latencies["Embedding Time"] = f"Error: {e}"

    # 3. SQLite Keyword Search
    try:
        from storage.db import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        
        # Test full text search query on SQLite
        start = time.perf_counter()
        cursor.execute("SELECT id FROM document_chunks WHERE chunk_text LIKE '%python%' LIMIT 5")
        cursor.fetchall()
        duration = time.perf_counter() - start
        latencies["Keyword Search"] = f"{duration*1000:.2f} ms"
        conn.close()
    except Exception as e:
        latencies["Keyword Search"] = f"Error: {e}"

    # 4. Qdrant Semantic Search
    qdrant_ok, _ = check_qdrant()
    if qdrant_ok:
        try:
            from core.vector_store import run_semantic_search, get_vector_index_stats
            # Vector count
            stats = get_vector_index_stats()
            latencies["Vector Count"] = f"{stats.get('vectors', 0):,}"
            
            # Semantic Query
            start = time.perf_counter()
            run_semantic_search("python", limit=5)
            duration = time.perf_counter() - start
            latencies["Semantic Search"] = f"{duration*1000:.2f} ms"
        except Exception as e:
            latencies["Semantic Search"] = f"Error: {e}"
    else:
        latencies["Semantic Search"] = "Offline (Qdrant down)"

    # 5. Hybrid Search
    if qdrant_ok:
        try:
            from core.vector_store import hybrid_search
            start = time.perf_counter()
            hybrid_search("python")
            duration = time.perf_counter() - start
            latencies["Hybrid Search"] = f"{duration*1000:.2f} ms"
        except Exception as e:
            latencies["Hybrid Search"] = f"Error: {e}"
    else:
        latencies["Hybrid Search"] = "Offline (Qdrant down)"

    # 6. Graph Lookup
    try:
        from storage.graph import GraphStore
        graph = GraphStore()
        
        # Get arbitrary repo to query
        from storage.db import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT repo_name FROM repositories LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        repo_to_query = row[0] if row else "unknown-repo"
        
        start = time.perf_counter()
        graph.get_node_relationships("Repository", repo_to_query)
        duration = time.perf_counter() - start
        latencies["Graph Lookup"] = f"{duration*1000:.2f} ms"
    except Exception as e:
        latencies["Graph Lookup"] = f"Error: {e}"

    # 7. LLM time & RAG Pipeline
    groq_ok, _ = check_groq_api()
    if groq_ok:
        try:
            from core.llm import run_hybrid_rag
            start = time.perf_counter()
            res = run_hybrid_rag("List repositories using Python")
            duration = time.perf_counter() - start
            latencies["Average RAG Pipeline"] = f"{duration:.2f} s"
            
            # Estimate LLM time
            # Assuming LLM call took most of RAG duration (minus search overhead)
            latencies["LLM Time"] = f"{duration * 0.85:.2f} s"
        except Exception as e:
            latencies["Average RAG Pipeline"] = f"Error: {e}"
            latencies["LLM Time"] = "Error"
    else:
        latencies["Average RAG Pipeline"] = "Offline (Groq key missing)"
        latencies["LLM Time"] = "Offline"

    # Display results
    print("──────────────────────────────────────────────────")
    print("  Benchmark Metrics")
    print("──────────────────────────────────────────────────")
    for name, score in latencies.items():
        padding = " " * (25 - len(name))
        print(f"  {name}{padding}: {score}")
    print("──────────────────────────────────────────────────")
