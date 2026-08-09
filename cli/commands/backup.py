"""
Command: memory-os backup

Creates a timestamped archive of the active workspace profile.
"""

import sys
import os
import zipfile
from datetime import datetime
from pathlib import Path
from infrastructure.workspace import (
    get_active_profile,
    get_backups_path,
    get_profile_path,
    get_logs_path
)


def execute(args):
    """Run the backup command."""
    active = get_active_profile()
    profile_path = get_profile_path(active)
    backups_dir = get_backups_path()
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"backup_{active}_{timestamp}.zip"

    print(f"Creating backup of active workspace profile '{active}'...")
    try:
        with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zipf:
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
