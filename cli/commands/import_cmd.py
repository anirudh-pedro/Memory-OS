"""
Command: memory-os import <file>

Safely unpacks and restores a previously exported workspace archive
into the active workspace profile.
"""

import sys
import json
import zipfile
import shutil
from pathlib import Path

from infrastructure.workspace import (
    get_active_profile,
    get_profile_path,
    get_db_path,
    get_qdrant_path,
    get_neo4j_path
)
from infrastructure.config import _get_config_path, get, load_config
from infrastructure.compose import compose_stop, compose_up, wait_for_services


def execute(args):
    """Run the import command."""
    import_path = Path(args.file)
    if not import_path.exists():
        print(f"❌ Import file '{import_path}' does not exist.")
        sys.exit(1)

    print(f"Verifying compatibility of '{import_path}'...")

    try:
        with zipfile.ZipFile(import_path, "r") as zipf:
            # 1. Read and Validate Metadata
            if "metadata.json" not in zipf.namelist():
                print("❌ Invalid archive: missing 'metadata.json'.")
                sys.exit(1)

            metadata_content = zipf.read("metadata.json").decode("utf-8")
            metadata = json.loads(metadata_content)

            archive_version = metadata.get("version", "0.0")
            if float(archive_version) > 1.0:
                print(f"❌ Incompatible archive version: {archive_version} (supported <= 1.0).")
                sys.exit(1)

            current_model = get("embeddings", "model", "all-MiniLM-L6-v2")
            archive_model = metadata.get("embedding_model")
            if archive_model and archive_model != current_model:
                print(f"⚠️ Warning: Embedding model mismatch.")
                print(f"  Archive uses:  {archive_model}")
                print(f"  Current config: {current_model}")
                print("  Importing may cause vector similarity search discrepancy.")

            # 2. Confirmation Prompt
            active_profile = get_active_profile()
            print(f"\n⚠️ WARNING: Importing will completely OVERWRITE data in the active workspace profile '{active_profile}'.")
            confirm = input(f"Are you sure you want to proceed? (y/N): ").strip().lower()
            if confirm != "y":
                print("Import cancelled.")
                return

            print("\nStopping local services to release database locks...")
            compose_stop()

            # 3. Clean up active profile paths
            profile_path = get_profile_path(active_profile)
            db_path = get_db_path(active_profile)
            qdrant_path = get_qdrant_path(active_profile)
            neo4j_path = get_neo4j_path(active_profile)
            config_path = _get_config_path()

            print("Cleaning existing database folders...")
            if db_path.exists():
                db_path.unlink()
            if qdrant_path.exists():
                shutil.rmtree(qdrant_path)
                qdrant_path.mkdir(parents=True, exist_ok=True)
            if neo4j_path.exists():
                shutil.rmtree(neo4j_path)
                neo4j_path.mkdir(parents=True, exist_ok=True)

            # 4. Unpack files
            print("Unpacking files from archive...")
            
            # config.toml
            if "config.toml" in zipf.namelist() and config_path:
                with open(config_path, "wb") as f:
                    f.write(zipf.read("config.toml"))
                print("  ✓ Restored config.toml")

            # workspace.db
            if "workspace.db" in zipf.namelist() and db_path:
                with open(db_path, "wb") as f:
                    f.write(zipf.read("workspace.db"))
                print("  ✓ Restored SQLite database")

            # Qdrant files
            qdrant_restored = 0
            for name in zipf.namelist():
                if name.startswith("qdrant/"):
                    target_file = qdrant_path / name[7:]
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(target_file, "wb") as f:
                        f.write(zipf.read(name))
                    qdrant_restored += 1
            if qdrant_restored > 0:
                print(f"  ✓ Restored {qdrant_restored} Qdrant index files")

            # Neo4j files
            neo4j_restored = 0
            for name in zipf.namelist():
                if name.startswith("neo4j/"):
                    target_file = neo4j_path / name[6:]
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(target_file, "wb") as f:
                        f.write(zipf.read(name))
                    neo4j_restored += 1
            if neo4j_restored > 0:
                print(f"  ✓ Restored {neo4j_restored} Neo4j database files")

            # 5. Restart Services
            print("\nStarting local services...")
            load_config()  # reload config from file
            if compose_up():
                print("Waiting for database health checks...")
                if wait_for_services(timeout=60):
                    print("✓ Database services started and healthy.")
                else:
                    print("⚠️ Services are starting, but health checks timed out. Run 'memory-os doctor' to check.")
            else:
                print("❌ Failed to start docker compose services.")

            print("──────────────────────────────────────────────────")
            print("🎉 Workspace imported and restored successfully!")
            print("──────────────────────────────────────────────────")

    except Exception as e:
        print(f"❌ Import failed: {e}")
        sys.exit(1)
