"""
Command: memory-os export <file>

Exports the current active workspace profile databases, configurations,
and metadata into a single compressed zip archive.
"""

import sys
import os
import json
import zipfile
from pathlib import Path
from datetime import datetime

from infrastructure.workspace import (
    get_active_profile,
    get_profile_path,
    get_db_path,
    get_qdrant_path,
    get_neo4j_path,
    get_workspace_size
)
from infrastructure.config import _get_config_path, get


def execute(args):
    """Run the export command."""
    export_path = Path(args.file)
    print(f"Exporting active workspace profile to '{export_path}'...")

    active_profile = get_active_profile()
    profile_path = get_profile_path(active_profile)
    db_path = get_db_path(active_profile)
    qdrant_path = get_qdrant_path(active_profile)
    neo4j_path = get_neo4j_path(active_profile)
    config_path = _get_config_path()

    if not profile_path.exists():
        print(f"❌ Active workspace profile '{active_profile}' does not exist.")
        sys.exit(1)

    # 1. Gather Metadata
    embedding_model = get("embeddings", "model", "all-MiniLM-L6-v2")
    metadata = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "active_profile": active_profile,
        "embedding_model": embedding_model,
        "storage_size_bytes": get_workspace_size(active_profile),
    }

    try:
        # Resolve export file parent directory exists
        if export_path.parent:
            export_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            # A. Metadata File
            zipf.writestr("metadata.json", json.dumps(metadata, indent=2))
            print("  ✓ Packed metadata.json")

            # B. Configuration File
            if config_path.exists():
                zipf.write(config_path, arcname="config.toml")
                print("  ✓ Packed config.toml")

            # C. SQLite Database
            if db_path.exists():
                zipf.write(db_path, arcname="workspace.db")
                print("  ✓ Packed SQLite database")

            # D. Qdrant storage folder recursively
            if qdrant_path.exists():
                qdrant_files_count = 0
                for root, _, files in os.walk(qdrant_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = Path("qdrant") / file_path.relative_to(qdrant_path)
                        zipf.write(file_path, arcname=arcname)
                        qdrant_files_count += 1
                print(f"  ✓ Packed {qdrant_files_count} Qdrant index files")

            # E. Neo4j storage folder recursively
            if neo4j_path.exists():
                neo4j_files_count = 0
                for root, _, files in os.walk(neo4j_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = Path("neo4j") / file_path.relative_to(neo4j_path)
                        zipf.write(file_path, arcname=arcname)
                        neo4j_files_count += 1
                print(f"  ✓ Packed {neo4j_files_count} Neo4j graph database files")

        print("──────────────────────────────────────────────────")
        print(f"🎉 Workspace profile '{active_profile}' exported successfully!")
        print(f"File: {export_path.resolve()}")
        print("──────────────────────────────────────────────────")

    except Exception as e:
        print(f"❌ Failed to export workspace: {e}")
        if export_path.exists():
            try:
                export_path.unlink()
            except OSError:
                pass
        sys.exit(1)
