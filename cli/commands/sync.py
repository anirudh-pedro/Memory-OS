"""
Command: memory-os sync

Synchronizes data from connected sources (GitHub, Gmail, Notion),
chunks documents, generates embeddings, and syncs databases.
"""

import sys
import time
import logging
import sqlite3
from storage.db import init_db, clear_all
from core.vector_store import run_reindexing, close_qdrant_client
from storage.graph import GraphStore
from connectors.github import sync_github
from connectors.gmail import sync_gmail
from connectors.notion import sync_notion


def execute(args):
    """Run the synchronization pipeline."""
    # Ensure database is initialized
    try:
        init_db()
    except sqlite3.OperationalError as e:
        print("----------------------------------")
        print("Workspace has not been initialized.")
        print("")
        print("Run:")
        print("memory-os init")
        print("----------------------------------")
        sys.exit(1)

    start_time = time.perf_counter()
    
    rebuild = getattr(args, "rebuild", False)
    source = getattr(args, "source", None)
    
    if rebuild:
        print("Performing full rebuild reset...")
        clear_all()
        close_qdrant_client()
        run_reindexing()
        GraphStore().clear_graph()

    # Sync based on source selection
    if source == "github":
        print("Syncing GitHub source...")
        sync_github()
    elif source == "gmail":
        print("Syncing Gmail source...")
        sync_gmail()
    elif source == "notion":
        print("Syncing Notion source...")
        sync_notion()
    else:
        print("Syncing all sources (GitHub, Gmail, Notion)...")
        sync_github()
        sync_gmail()
        sync_notion()

    print("Running document chunking and vector reindexing...")
    run_reindexing()

    print("Extracting and syncing knowledge graph relationships...")
    GraphStore().extract_and_sync_graph()

    duration = time.perf_counter() - start_time
    print(f"\nSync complete. Total Duration: {duration:.2f}s")
    logging.getLogger("main").info(f"Sync completed in {duration:.2f}s")
