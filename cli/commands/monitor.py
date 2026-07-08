"""
Command: memory-os monitor

Displays system observability and performance latency diagnostics.
"""

from infrastructure.observability import get_performance_summary


def execute(args):
    """Run the monitor command."""
    print("──────────────────────────────────────────────────")
    print("  Memory-OS Observability Dashboard")
    print("──────────────────────────────────────────────────")
    
    summary = get_performance_summary()
    
    # Format and present results
    print("  Sync Performance:")
    print(f"    Total Sync Runs:      {summary['sync_count']}")
    print(f"    Last Sync Duration:   {summary['last_sync_duration']:.2f}s")
    print(f"    Avg Sync Duration:    {summary['avg_sync_duration']:.2f}s")
    
    print("\n  Data Insertion & indexing Latencies:")
    if summary['avg_chunk_latency'] > 0:
        print(f"    Avg Embedding Time:   {summary['avg_chunk_latency']*1000:.1f}ms / chunk")
    else:
        print("    Avg Embedding Time:   N/A (no events recorded)")
        
    if summary['avg_vector_latency'] > 0:
        print(f"    Qdrant Upload Time:   {summary['avg_vector_latency']*1000:.1f}ms / vector")
    else:
        print("    Qdrant Upload Time:   N/A")
        
    if summary['avg_neo4j_sync'] > 0:
        print(f"    Neo4j Graph Sync:     {summary['avg_neo4j_sync']:.2f}s (Total Nodes: {summary['total_nodes_synced']}, Rels: {summary['total_rels_synced']})")
    else:
        print("    Neo4j Graph Sync:     N/A")
        
    print("\n  LLM & RAG Query Latencies:")
    print(f"    Total LLM Queries:    {summary['llm_call_count']}")
    if summary['avg_llm_duration'] > 0:
        print(f"    Avg LLM Call Time:    {summary['avg_llm_duration']:.2f}s")
    else:
        print("    Avg LLM Call Time:    N/A")
        
    if summary['avg_retrieval_duration'] > 0:
        print(f"    Avg Retrieval Time:   {summary['avg_retrieval_duration']*1000:.1f}ms (hybrid)")
    else:
        print("    Avg Retrieval Time:   N/A")
        
    if summary['avg_rag_duration'] > 0:
        print(f"    Average RAG Time:     {summary['avg_rag_duration']:.2f}s")
    else:
        print("    Average RAG Time:     N/A")

    print("──────────────────────────────────────────────────")
