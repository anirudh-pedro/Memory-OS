import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infrastructure.compose import ComposeManager


def test_compose_file_generation(tmp_path):
    """Test compose file generation and validation."""
    manager = ComposeManager(workspace_root=tmp_path)
    
    with patch("infrastructure.workspace.get_workspace_root", return_value=tmp_path), \
         patch("infrastructure.workspace.get_active_profile", return_value="test-profile"), \
         patch("infrastructure.config.get_config", return_value={}):
        
        compose_path = manager.get_compose_path()
        assert not compose_path.exists()
        
        manager.generate_compose(profile="test-profile")
        assert compose_path.exists()
        
        content = compose_path.read_text(encoding="utf-8")
        assert "memory-os-neo4j-test-profile" in content
        assert "memory-os-qdrant-test-profile" in content
        assert "test-profile/neo4j" in content
        assert "test-profile/qdrant" in content


def test_compose_file_regeneration_on_corrupted_yaml(tmp_path):
    """Test compose file validation automatically regenerates corrupted compose files."""
    manager = ComposeManager(workspace_root=tmp_path)
    compose_path = manager.get_compose_path()
    
    with patch("infrastructure.workspace.get_workspace_root", return_value=tmp_path), \
         patch("infrastructure.workspace.get_active_profile", return_value="test-profile"), \
         patch("infrastructure.config.get_config", return_value={}):
        
        # Write corrupted YAML
        compose_path.write_text("invalid_yaml: { [ : missing_bracket", encoding="utf-8")
        
        # Validate should detect parsing error and regenerate it
        manager.validate(profile="test-profile")
        
        content = compose_path.read_text(encoding="utf-8")
        assert "services:" in content
        assert "neo4j:" in content


def test_first_install_behavior(tmp_path):
    """Test ComposeManager creates missing workspace directories on first install validation."""
    manager = ComposeManager(workspace_root=tmp_path)
    compose_path = manager.get_compose_path()
    
    with patch("infrastructure.workspace.get_workspace_root", return_value=tmp_path), \
         patch("infrastructure.workspace.get_active_profile", return_value="first-profile"), \
         patch("infrastructure.config.get_config", return_value={}):
        
        assert not compose_path.exists()
        
        # Calling validate should create missing directory paths and compose file
        manager.validate(profile="first-profile")
        
        assert compose_path.exists()
        assert (tmp_path / "workspaces" / "first-profile" / "neo4j").exists()
        assert (tmp_path / "workspaces" / "first-profile" / "qdrant").exists()


def test_multiple_profiles_and_workspace_switching(tmp_path):
    """Test generating compose configuration for multiple profiles maps volumes correctly."""
    manager = ComposeManager(workspace_root=tmp_path)
    compose_path = manager.get_compose_path()
    
    with patch("infrastructure.workspace.get_workspace_root", return_value=tmp_path), \
         patch("infrastructure.config.get_config", return_value={}):
        # Switch to profile A
        manager.generate_compose(profile="profile-A")
        content_a = compose_path.read_text(encoding="utf-8")
        assert "profile-A/neo4j" in content_a
        assert "profile-A/qdrant" in content_a
        
        # Switch to profile B
        manager.generate_compose(profile="profile-B")
        content_b = compose_path.read_text(encoding="utf-8")
        assert "profile-B/neo4j" in content_b
        assert "profile-B/qdrant" in content_b


def test_docker_compose_invocation(tmp_path):
    """Test that docker compose commands specify the generated compose file path explicitly."""
    manager = ComposeManager(workspace_root=tmp_path)
    
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc
        
        with patch("infrastructure.workspace.get_workspace_root", return_value=tmp_path), \
             patch("infrastructure.workspace.get_active_profile", return_value="default"), \
             patch("infrastructure.config.get_config", return_value={}):
            
            # Start services
            manager.up(profile="default")
            
            # Verify subprocess run args contains -f and points to workspace compose file
            args = mock_run.call_args[0][0]
            assert "docker" in args
            assert "compose" in args
            assert "-f" in args
            assert str(manager.get_compose_path()) in args


def test_successful_vs_failed_startup(tmp_path, capsys):
    """Test docker compose up execution diagnostics on success vs failure."""
    manager = ComposeManager(workspace_root=tmp_path)
    
    # 1. Success case
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc
        
        with patch("infrastructure.workspace.get_workspace_root", return_value=tmp_path), \
             patch("infrastructure.workspace.get_active_profile", return_value="default"), \
             patch("infrastructure.config.get_config", return_value={}):
            
            res = manager.up(profile="default")
            assert res is True
            captured = capsys.readouterr()
            assert "Docker command:" not in captured.out

    # 2. Failure case
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "stdout logs"
        mock_proc.stderr = "Error: daemon is offline"
        mock_proc.args = ["docker", "compose", "-f", "some-path", "up", "-d"]
        mock_run.return_value = mock_proc
        
        with patch("infrastructure.workspace.get_workspace_root", return_value=tmp_path), \
             patch("infrastructure.workspace.get_active_profile", return_value="default"), \
             patch("infrastructure.config.get_config", return_value={}):
            
            res = manager.up(profile="default")
            assert res is False
            captured = capsys.readouterr()
            
            # Diagnostic check outputs standard blocks
            assert "Docker command:" in captured.out
            assert "Exit code:" in captured.out
            assert "Error: daemon is offline" in captured.out
            assert "Recommendation:" in captured.out
