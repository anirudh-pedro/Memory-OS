"""
Unit tests for Phase 2 command modules: init, start, and stop.
Mocks out external systems like Docker, Compose, and interactive prompts.
"""

import sys
import unittest
from unittest.mock import patch, MagicMock


class TestPhase2Commands(unittest.TestCase):
    """Test suite for Phase 2 command execution logic."""

    @patch("cli.commands.init.get_input")
    @patch("cli.commands.init.check_docker")
    @patch("cli.commands.init.check_neo4j")
    @patch("cli.commands.init.check_qdrant")
    @patch("cli.commands.init.ensure_workspace")
    @patch("cli.commands.init.generate_default_config")
    @patch("cli.commands.init.save_config")
    @patch("cli.commands.init.load_config")
    @patch("cli.commands.init.compose_up")
    @patch("cli.commands.init.wait_for_services")
    @patch("cli.commands.init.init_db")
    @patch("cli.commands.init.Embedder")
    @patch("cli.commands.init.run_all_checks")
    def test_init_command_success(
        self,
        mock_run_all_checks,
        mock_embedder_class,
        mock_init_db,
        mock_wait_for_services,
        mock_compose_up,
        mock_load_config,
        mock_save_config,
        mock_generate_config,
        mock_ensure_workspace,
        mock_qdrant,
        mock_neo,
        mock_docker,
        mock_get_input,
    ):
        """Test successful init run with mocks."""
        # Setup mocks
        mock_docker.return_value = (True, "Ready")
        mock_neo.return_value = (False, "Offline")
        mock_qdrant.return_value = (False, "Offline")
        
        # User inputs: Neo4j password, Groq key, Composio key, download model, connect toolkits (mock n for skip)
        mock_get_input.side_effect = ["memory_neo", "gsk_groq", "ak_composio", "y", "n"]
        mock_compose_up.return_value = True
        mock_wait_for_services.return_value = True
        mock_run_all_checks.return_value = [("SQLite", True, "Healthy"), ("Docker", True, "Healthy")]
        
        mock_embedder_inst = MagicMock()
        mock_embedder_class.return_value = mock_embedder_inst

        # Import and execute
        from cli.commands.init import execute
        execute(None)

        # Assert calls
        mock_docker.assert_called_once()
        mock_neo.assert_called_once()
        mock_qdrant.assert_called_once()
        mock_ensure_workspace.assert_called_once_with("default")
        mock_generate_config.assert_called_once()
        mock_save_config.assert_called_once()
        mock_compose_up.assert_called_once()
        mock_wait_for_services.assert_called_once_with(timeout=60)
        mock_init_db.assert_called_once()
        mock_embedder_class.assert_called_once()

    @patch("cli.commands.start.compose_up")
    @patch("cli.commands.start.wait_for_services")
    def test_start_command(self, mock_wait_for_services, mock_compose_up):
        """Test start command execution."""
        mock_compose_up.return_value = True
        mock_wait_for_services.return_value = True

        from cli.commands.start import execute
        execute(None)

        mock_compose_up.assert_called_once()
        mock_wait_for_services.assert_called_once_with(timeout=60)

    @patch("cli.commands.stop.compose_stop")
    def test_stop_command(self, mock_compose_stop):
        """Test stop command execution."""
        mock_compose_stop.return_value = True

        from cli.commands.stop import execute
        execute(None)

        mock_compose_stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
