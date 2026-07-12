"""
Command: memory-os workspace create|switch|list|delete|info

Provides management of active workspaces and profile structures.
"""

import sys
import os
from datetime import datetime
from infrastructure.workspace import (
    get_active_profile,
    list_profiles,
    create_profile,
    delete_profile,
    set_active_profile,
    get_workspace_size,
    get_profile_path,
    get_db_path
)


def execute(args):
    """Run the workspace command."""
    action = args.workspace_action

    if action == "list":
        profiles = list_profiles()
        active = get_active_profile()
        print("─────────────────────────────")
        print("  Memory-OS Workspace Profiles")
        print("─────────────────────────────")
        for p in profiles:
            prefix = "* " if p == active else "  "
            print(f"{prefix}{p}")
        print("─────────────────────────────")

    elif action == "create":
        name = args.name
        try:
            create_profile(name)
            print(f"✓ Workspace profile '{name}' created successfully.")
        except Exception as e:
            print(f"❌ Failed to create workspace profile: {e}")
            sys.exit(1)

    elif action == "switch":
        name = args.name
        try:
            set_active_profile(name)
            print(f"✓ Switched active workspace profile to '{name}'.")
        except Exception as e:
            print(f"❌ Failed to switch workspace profile: {e}")
            sys.exit(1)

    elif action == "delete":
        name = args.name
        active = get_active_profile()
        if name == active:
            print(f"❌ Cannot delete the currently active workspace profile '{name}'. Switch first.")
            sys.exit(1)

        confirm = input(f"⚠️ Are you sure you want to delete workspace profile '{name}' and ALL its databases? (y/N): ").strip().lower()
        if confirm == "y":
            try:
                delete_profile(name)
                print(f"✓ Workspace profile '{name}' deleted successfully.")
            except Exception as e:
                print(f"❌ Failed to delete workspace profile: {e}")
                sys.exit(1)
        else:
            print("Deletion cancelled.")

    elif action == "info":
        active = get_active_profile()
        path = get_profile_path(active)
        db_file = get_db_path(active)

        # Retrieve counts
        repos = 0
        vectors = 0
        nodes = 0
        last_sync = "Never"

        try:
            from storage.db import get_repo_count
            repos = get_repo_count()
        except Exception:
            pass

        try:
            from core.vector_store import get_vector_index_stats
            vectors = get_vector_index_stats().get("vectors", 0)
        except Exception:
            pass

        try:
            from storage.graph import GraphStore
            graph = GraphStore()
            if graph.is_fallback:
                from storage.db import get_connection
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM graph_nodes")
                nodes = cursor.fetchone()[0]
                conn.close()
            else:
                with graph.driver.session() as session:
                    nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        except Exception:
            pass

        # Calculate last sync timestamp from DB file modification or max chunk created_at
        if db_file.exists():
            try:
                from storage.db import get_connection
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(created_at) FROM document_chunks")
                row = cursor.fetchone()
                if row and row[0]:
                    last_sync = row[0][:19].replace("T", " ")
                else:
                    mtime = os.path.getmtime(db_file)
                    last_sync = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                conn.close()
            except Exception:
                import os
                from datetime import datetime
                mtime = os.path.getmtime(db_file)
                last_sync = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

        size_bytes = get_workspace_size(active)
        if size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.0f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            size_str = f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

        print("──────────────────────────────────────────────────")
        print(f"  Memory-OS Workspace Info: {active}")
        print("──────────────────────────────────────────────────")
        print(f"  Profile Location:  {path.resolve()}")
        print(f"  Repositories:      {repos}")
        print(f"  Vectors:           {vectors}")
        print(f"  Graph Nodes:       {nodes}")
        print(f"  Disk Storage Size: {size_str}")
        print(f"  Last Sync Time:    {last_sync}")
        print("──────────────────────────────────────────────────")

    else:
        print("Usage: memory-os workspace create|switch|list|delete|info")
