import os
import sys
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.commands.status import execute as execute_status
from cli.commands.doctor import execute as execute_doctor
from cli.commands.init import execute as execute_init

class DummyArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

def test_status_empty_workspace(tmp_path, capsys):
    """Test memory-os status when the workspace is empty (0 records)."""
    db_file = tmp_path / "workspace.db"
    
    # We call init_db to create empty tables
    from storage.db import init_db
    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
        init_db()
        
        # Mock vector store stats and workspace active profile
        with patch("infrastructure.workspace.get_db_path", return_value=db_file), \
             patch("infrastructure.workspace.get_active_profile", return_value="default"), \
             patch("core.vector_store.get_vector_index_stats", return_value={"vectors": 0, "embedding_model": "N/A"}):
            
            execute_status(DummyArgs())
            captured = capsys.readouterr()
            
            assert "Workspace Profile : default" in captured.out
            assert "Repositories : 0" in captured.out
            assert "Workspace is initialized but contains no indexed data." in captured.out
            assert "memory-os sync" in captured.out

def test_status_missing_sqlite_db(tmp_path, capsys):
    """Test memory-os status when SQLite DB is missing."""
    db_file = tmp_path / "non_existent_dir" / "workspace.db"
    
    with patch("infrastructure.workspace.get_db_path", return_value=db_file), \
         patch("infrastructure.workspace.get_active_profile", return_value="default"):
        
        # Make db_file non-existent
        if db_file.exists():
            db_file.unlink()
            
        execute_status(DummyArgs())
        captured = capsys.readouterr()
        
        assert "Workspace not initialized." in captured.out
        assert "memory-os init" in captured.out

def test_status_missing_tables(tmp_path, capsys):
    """Test memory-os status when SQLite DB exists but has missing tables / OperationalError."""
    db_file = tmp_path / "workspace.db"
    # Create empty db file with no tables
    db_file.touch()
    
    with patch("infrastructure.workspace.get_db_path", return_value=db_file), \
         patch("infrastructure.workspace.get_active_profile", return_value="default"), \
         patch("storage.db.get_repo_count", side_effect=sqlite3.OperationalError("no such table: repositories")), \
         patch("storage.db.init_db", side_effect=sqlite3.OperationalError("schema error")):
         
        execute_status(DummyArgs())
        captured = capsys.readouterr()
        
        assert "Workspace not initialized." in captured.out or "Workspace has not been initialized." in captured.out
        assert "memory-os init" in captured.out

def test_init_missing_docker(capsys):
    """Test memory-os init when Docker Desktop is not running."""
    with patch("infrastructure.docker.check_docker_installed", return_value=(True, "Docker version 24.0.7")), \
         patch("infrastructure.docker.check_docker_compose_installed", return_value=(True, "Docker Compose version 2.23.3")), \
         patch("infrastructure.docker.check_docker_running", return_value=False):
         
        with pytest.raises(SystemExit) as excinfo:
            execute_init(DummyArgs())
            
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Docker Desktop is not running." in captured.out
        assert "Start Docker Desktop and rerun:" in captured.out
        assert "memory-os init" in captured.out

def test_doctor_recommendations(capsys):
    """Test doctor command provides the right actionable recommendations when services are down."""
    with patch("infrastructure.health.run_all_checks", return_value=[
        ("SQLite", False, "File not found"),
        ("Neo4j", False, "Connection refused"),
        ("Qdrant", False, "Connection refused"),
        ("Groq", False, "No API key"),
        ("Composio", False, "No API key"),
    ]):
        execute_doctor(DummyArgs())
        captured = capsys.readouterr()
        
        assert "Workspace not initialized. Run memory-os init." in captured.out
        assert "Run:\n  memory-os start" in captured.out
        assert "memory-os config set groq.api_key <key>" in captured.out
        assert "memory-os config set composio.api_key <key>" in captured.out
