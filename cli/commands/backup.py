"""
Command: memory-os backup

Creates a timestamped archive of the active workspace profile.
"""

import sys
import os
import json
import zipfile
from datetime import datetime
from pathlib import Path
from infrastructure.workspace import (
    get_active_profile,
    get_backups_path,
    get_profile_path,
    get_db_path,
    get_qdrant_path,
    get_neo4j_path,
    get_logs_path,
    get_workspace_size
)
from infrastructure.config import _get_config_path, get


def execute(args):
    """Run the backup command."""
    active = get_active_profile()
    profile_path = get_profile_path(active)
    db_path = get_db_path(active)
    qdrant_path = get_qdrant_path(active)
    neo4j_path = get_neo4j_path(active)
    config_path = _get_config_path()
    backups_dir = get_backups_path()
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"backup_{active}_{timestamp}.zip"

    print(f"Creating backup of active workspace profile '{active}'...")
    try:
        embedding_model = get("embeddings", "model", "all-MiniLM-L6-v2")
        metadata = {
            "version": "1.0",
            "backed_up_at": datetime.now().isoformat(),
            "active_profile": active,
            "embedding_model": embedding_model,
            "storage_size_bytes": get_workspace_size(active),
        }

        with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Metadata
            zipf.writestr("metadata.json", json.dumps(metadata, indent=2))

            # Configuration
            if config_path.exists():
                zipf.write(config_path, arcname="config.toml")

            # SQLite Database
            if db_path.exists():
                zipf.write(db_path, arcname="workspace.db")

            # Qdrant files
            if qdrant_path.exists():
                for root, _, files in os.walk(qdrant_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = Path("qdrant") / file_path.relative_to(qdrant_path)
                        zipf.write(file_path, arcname=arcname)

            # Neo4j files
            if neo4j_path.exists():
                for root, _, files in os.walk(neo4j_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = Path("neo4j") / file_path.relative_to(neo4j_path)
                        zipf.write(file_path, arcname=arcname)

            # Workspace directory contents for legacy compatibility
            if profile_path.exists():
                for root, _, files in os.walk(profile_path):
                    for f in files:
                        fp = Path(root) / f
                        arcname = Path("workspace") / fp.relative_to(profile_path)
                        zipf.write(fp, arcname=arcname)

            include_logs = getattr(args, "include_logs", False)
            if include_logs:
                logs_path = get_logs_path()
                if logs_path.exists():
                    for root, _, files in os.walk(logs_path):
                        for f in files:
                            fp = Path(root) / f
                            arcname = Path("logs") / fp.relative_to(logs_path)
                            zipf.write(fp, arcname=arcname)

        print("──────────────────────────────────────────────────")
        print(f"🎉 Backup created successfully!")
        print(f"File: {backup_file.resolve()}")
        print("──────────────────────────────────────────────────")
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        sys.exit(1)
