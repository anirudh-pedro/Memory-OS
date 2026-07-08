"""
Infrastructure: Workspace directory and profile management.

Manages the ~/.memory-os/ directory tree and workspace profiles
(default, work, personal, etc.).
"""

import os
import shutil
from pathlib import Path


def get_workspace_root() -> Path:
    """Return the root workspace directory (~/.memory-os/)."""
    root = os.getenv("MEMORY_OS_WORKSPACE", "~/.memory-os")
    return Path(os.path.expanduser(root))


def ensure_workspace(profile: str = "default"):
    """Create the full workspace directory tree for a profile.

    Creates:
        ~/.memory-os/
        ├── config.toml         (not created here, handled by config.py)
        ├── active_workspace
        ├── workspaces/
        │   └── <profile>/
        │       ├── workspace.db  (created by SQLite on first use)
        │       ├── qdrant/
        │       ├── neo4j/
        │       └── embeddings/
        ├── logs/
        ├── cache/
        └── backups/
    """
    root = get_workspace_root()

    # Top-level shared directories
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "cache").mkdir(parents=True, exist_ok=True)
    (root / "backups").mkdir(parents=True, exist_ok=True)
    (root / "workspaces").mkdir(parents=True, exist_ok=True)

    # Profile-specific directories
    profile_dir = root / "workspaces" / profile
    (profile_dir / "qdrant").mkdir(parents=True, exist_ok=True)
    (profile_dir / "neo4j").mkdir(parents=True, exist_ok=True)
    (profile_dir / "embeddings").mkdir(parents=True, exist_ok=True)

    # Set active workspace if no active_workspace file exists
    active_file = root / "active_workspace"
    if not active_file.exists():
        active_file.write_text(profile, encoding="utf-8")


def get_active_profile() -> str:
    """Read the currently active workspace profile name."""
    active_file = get_workspace_root() / "active_workspace"
    if active_file.exists():
        return active_file.read_text(encoding="utf-8").strip()
    return "default"


def set_active_profile(name: str):
    """Set the active workspace profile."""
    root = get_workspace_root()
    profile_dir = root / "workspaces" / name
    if not profile_dir.exists():
        raise FileNotFoundError(f"Workspace profile '{name}' does not exist.")
    active_file = root / "active_workspace"
    active_file.write_text(name, encoding="utf-8")


def list_profiles() -> list[str]:
    """List all workspace profile names."""
    workspaces_dir = get_workspace_root() / "workspaces"
    if not workspaces_dir.exists():
        return []
    return sorted([
        d.name for d in workspaces_dir.iterdir()
        if d.is_dir()
    ])


def create_profile(name: str):
    """Create a new workspace profile."""
    root = get_workspace_root()
    profile_dir = root / "workspaces" / name
    if profile_dir.exists():
        raise FileExistsError(f"Workspace profile '{name}' already exists.")
    ensure_workspace(profile=name)


def delete_profile(name: str):
    """Delete a workspace profile directory."""
    if name == get_active_profile():
        raise ValueError(f"Cannot delete the active workspace profile '{name}'. Switch first.")
    profile_dir = get_workspace_root() / "workspaces" / name
    if not profile_dir.exists():
        raise FileNotFoundError(f"Workspace profile '{name}' does not exist.")
    shutil.rmtree(profile_dir)


def get_profile_path(name: str | None = None) -> Path:
    """Return the path for a specific profile (or the active one)."""
    if name is None:
        name = get_active_profile()
    return get_workspace_root() / "workspaces" / name


def get_db_path(profile: str | None = None) -> Path:
    """Return the SQLite database path for a workspace profile."""
    return get_profile_path(profile) / "workspace.db"


def get_qdrant_path(profile: str | None = None) -> Path:
    """Return the Qdrant storage path for a workspace profile."""
    return get_profile_path(profile) / "qdrant"


def get_neo4j_path(profile: str | None = None) -> Path:
    """Return the Neo4j data path for a workspace profile."""
    return get_profile_path(profile) / "neo4j"


def get_logs_path() -> Path:
    """Return the shared logs directory path."""
    return get_workspace_root() / "logs"


def get_backups_path() -> Path:
    """Return the shared backups directory path."""
    return get_workspace_root() / "backups"


def get_cache_path() -> Path:
    """Return the shared cache directory path."""
    return get_workspace_root() / "cache"


def get_workspace_size(profile: str | None = None) -> int:
    """Calculate total disk usage in bytes for a workspace profile."""
    path = get_profile_path(profile) if profile else get_workspace_root()
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total
