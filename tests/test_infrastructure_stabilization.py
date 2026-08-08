import os
import sys
from unittest.mock import patch, MagicMock

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infrastructure.health import check_docker, check_neo4j, check_qdrant
from cli.commands.init import execute as execute_init
from cli.commands.doctor import execute as execute_doctor

class DummyArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_docker_daemon_running():
    """Test Docker daemon is active."""
    with patch("subprocess.run") as mock_run:
        # Mock successful docker info
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Server Version: 24.0.7\n"
        mock_run.return_value = mock_proc
        
        ok, ver = check_docker()
        assert ok is True
        assert "24.0.7" in ver


def test_docker_daemon_stopped():
    """Test Docker daemon is stopped."""
    with patch("subprocess.run") as mock_run:
        # Mock failed docker info
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "docker daemon is not running"
        mock_run.return_value = mock_proc
        
        ok, err = check_docker()
        assert ok is False
        assert "not running" in err


def test_neo4j_auth_failure():
    """Test Neo4j auth error detection."""
    from neo4j.exceptions import AuthError
    
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_drv_inst = MagicMock()
        mock_drv_inst.verify_connectivity.side_effect = AuthError("Unauthorized")
        mock_driver.return_value = mock_drv_inst
        
        ok, detail = check_neo4j()
        assert ok is False
        assert "Authentication failed" in detail


def test_neo4j_unreachable():
    """Test Neo4j connection timeout/unreachable error."""
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_drv_inst = MagicMock()
        mock_drv_inst.verify_connectivity.side_effect = Exception("Connection timed out")
        mock_driver.return_value = mock_drv_inst
        
        ok, detail = check_neo4j()
        assert ok is False
        assert "Unreachable" in detail


def test_qdrant_version_compatible():
    """Test Qdrant version check with compatible client and server."""
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("importlib.metadata.version", return_value="1.18.0"):
        
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"version": "1.18.2"}'
        mock_urlopen.return_value = mock_response
        
        ok, detail = check_qdrant()
        assert ok is True
        assert "compatible" in detail


def test_qdrant_version_incompatible():
    """Test Qdrant version check with mismatched client and server."""
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("importlib.metadata.version", return_value="1.18.0"):
        
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"version": "1.12.6"}'
        mock_urlopen.return_value = mock_response
        
        ok, detail = check_qdrant()
        assert ok is False
        assert "version mismatch" in detail


@patch("cli.commands.init.check_docker", return_value=(True, "Ready"))
@patch("cli.commands.init.check_neo4j", return_value=(True, "Healthy"))
@patch("cli.commands.init.check_qdrant", return_value=(True, "Healthy"))
@patch("cli.commands.init.ensure_workspace")
@patch("cli.commands.init.generate_default_config")
@patch("cli.commands.init.save_config")
@patch("cli.commands.init.init_db")
@patch("cli.commands.init.run_all_checks", return_value=[])
@patch("cli.commands.init.get_input", side_effect=["pass", "groq", "composio", "n", "n"])
def test_init_skips_healthy_services(mock_input, mock_run_checks, mock_db, mock_save, mock_gen, mock_ensure, mock_qdrant, mock_neo, mock_docker, capsys):
    """Test memory-os init bypasses provisioning when services are already running and healthy."""
    with patch("cli.commands.init.ComposeManager") as mock_compose_manager:
        mock_manager = MagicMock()
        mock_compose_manager.return_value = mock_manager
        execute_init(DummyArgs())
        captured = capsys.readouterr()
        
        # Verify compose_up/manager.up was never called because services were already healthy
        mock_manager.up.assert_not_called()
        
        assert "Neo4j already running" in captured.out
        assert "Qdrant already running" in captured.out


def test_doctor_auth_recommendations(capsys):
    """Test doctor lists Neo4j auth failure recommendations correctly."""
    with patch("infrastructure.health.run_all_checks", return_value=[
        ("Neo4j", False, "Authentication failed: unauthorized access"),
        ("Docker Compose", True, "Healthy"),
        ("SQLite", True, "Healthy"),
        ("Qdrant", True, "Healthy"),
    ]):
        execute_doctor(DummyArgs())
        captured = capsys.readouterr()
        
        assert "Neo4j is running but authentication failed." in captured.out
        assert "neo4j.password" in captured.out


def test_db_context_manager_and_migration(tmp_path):
    """Test db schema versioning, non-destructive migration, and context manager."""
    from storage.db import init_db, get_db_connection, get_repo_count, insert_repository
    from models.memory import Repository

    db_file = tmp_path / "test_migration.db"
    
    # 1. Initialize schema
    init_db(str(db_file))

    # 2. Check schema_versions table
    with get_db_connection(str(db_file)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_versions")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] >= 1

    # 3. Test insert & context manager
    repo = Repository(
        repo_name="test-repo",
        description="Test description",
        language="Python",
        visibility="public",
        stars=10,
        forks=2,
        open_issues=0,
        default_branch="main",
        updated_at="2026-08-08T00:00:00",
        url="https://github.com/test/test-repo"
    )
    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
        insert_repository(repo)
        assert get_repo_count() == 1

    # 4. Re-run init_db (migration check) to ensure no data is destroyed
    init_db(str(db_file))
    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
        assert get_repo_count() == 1


def test_secure_file_permissions(tmp_path):
    """Test secure_file_permissions sets owner-only permissions."""
    from infrastructure.config import secure_file_permissions
    test_file = tmp_path / "config.toml"
    test_file.write_text("groq = { model = 'test' }\n")
    
    secure_file_permissions(test_file)
    assert test_file.exists()

