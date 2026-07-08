"""
Command: memory-os status

Shows workspace and service status information.
"""


def execute(args):
    """Run the status command."""
    from storage.db import (
        get_repo_count,
        get_email_count,
        get_repository_document_count,
        get_document_chunk_count,
    )
    from core.vector_store import get_vector_index_stats

    print("─────────────────────────────")
    print("  memory-os status")
    print("─────────────────────────────")

    # Database counts
    repos = get_repo_count()
    docs = get_repository_document_count()
    emails = get_email_count()
    chunks = get_document_chunk_count()

    print(f"  Repositories     {repos}")
    print(f"  Documents        {docs}")
    print(f"  Emails           {emails}")
    print(f"  Chunks           {chunks}")

    # Vector index
    stats = get_vector_index_stats()
    print(f"  Vectors          {stats.get('vectors', 0)}")
    print(f"  Embedding Model  {stats.get('embedding_model', 'N/A')}")

    print("─────────────────────────────")
