"""
Command: memory-os status

Shows workspace and service status information.
"""


def execute(args):
    """Run the status command."""
    import logging
    from infrastructure.workspace import get_active_profile, get_db_path

    active = get_active_profile()
    db_file = get_db_path(active)

    # If the workspace database doesn't exist, show not initialized
    if not db_file.exists():
        print("----------------------------------")
        print("Workspace not initialized.")
        print("")
        print("Run:")
        print("memory-os init")
        print("----------------------------------")
        return

    # Call init_db to ensure schema exists
    try:
        from storage.db import init_db
        init_db()
    except Exception as e:
        logging.getLogger("cli.status").exception("Failed to initialize database schema")
        print("----------------------------------")
        print("Workspace not initialized.")
        print("")
        print("Run:")
        print("memory-os init")
        print("----------------------------------")
        return

    from storage.db import (
        get_repo_count,
        get_email_count,
        get_repository_document_count,
        get_document_chunk_count,
    )
    from core.vector_store import get_vector_index_stats

    try:
        repos = get_repo_count()
        docs = get_repository_document_count()
        emails = get_email_count()
        chunks = get_document_chunk_count()
        stats = get_vector_index_stats()
        vectors = stats.get('vectors', 0)
        embedding_model = stats.get('embedding_model', 'N/A')
    except Exception as e:
        logging.getLogger("cli.status").exception("SQLite OperationalError in status")
        print("----------------------------------")
        print("Workspace has not been initialized.")
        print("")
        print("Run:")
        print("memory-os init")
        print("----------------------------------")
        return

    # Check if empty (repos=0, docs=0, emails=0, vectors=0)
    if repos == 0 and docs == 0 and emails == 0 and vectors == 0:
        print("----------------------------------")
        print(f"Workspace Profile : {active}")
        print("")
        print(f"Repositories : 0")
        print(f"Documents    : 0")
        print(f"Emails       : 0")
        print(f"Vectors      : 0")
        print(f"Embedding Model : {embedding_model}")
        print("")
        print("Workspace is initialized but contains no indexed data.")
        print("")
        print("Run:")
        print("memory-os sync")
        print("----------------------------------")
    else:
        print("─────────────────────────────")
        print("  memory-os status")
        print("─────────────────────────────")
        print(f"  Repositories     {repos}")
        print(f"  Documents        {docs}")
        print(f"  Emails           {emails}")
        print(f"  Chunks           {chunks}")
        print(f"  Vectors          {vectors}")
        print(f"  Embedding Model  {embedding_model}")
        print("─────────────────────────────")

