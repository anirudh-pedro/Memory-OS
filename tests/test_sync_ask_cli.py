"""
Unit and integration tests for sync, ask commands, and the interactive REPL.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DummyArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestSyncAskCLI(unittest.TestCase):
    """Test suite verifying sync and ask CLI command routing and logic."""

    @patch("cli.commands.sync.init_db")
    @patch("cli.commands.sync.sync_github")
    @patch("cli.commands.sync.sync_gmail")
    @patch("cli.commands.sync.sync_notion")
    @patch("cli.commands.sync.run_reindexing")
    @patch("cli.commands.sync.GraphStore")
    def test_sync_command_all_sources(
        self, mock_graph_store_class, mock_run_reindexing, mock_sync_notion, mock_sync_gmail, mock_sync_github, mock_init_db
    ):
        """Test memory-os sync command runs sync for all sources."""
        mock_graph_inst = MagicMock()
        mock_graph_store_class.return_value = mock_graph_inst

        from cli.commands.sync import execute as execute_sync

        args = DummyArgs(rebuild=False, source=None)
        execute_sync(args)

        mock_init_db.assert_called_once()
        mock_sync_github.assert_called_once()
        mock_sync_gmail.assert_called_once()
        mock_sync_notion.assert_called_once()
        mock_run_reindexing.assert_called_once()
        mock_graph_inst.extract_and_sync_graph.assert_called_once()

    @patch("cli.commands.sync.init_db")
    @patch("cli.commands.sync.sync_github")
    @patch("cli.commands.sync.run_reindexing")
    @patch("cli.commands.sync.GraphStore")
    def test_sync_command_single_source(
        self, mock_graph_store_class, mock_run_reindexing, mock_sync_github, mock_init_db
    ):
        """Test memory-os sync command can sync only a single source."""
        mock_graph_inst = MagicMock()
        mock_graph_store_class.return_value = mock_graph_inst

        from cli.commands.sync import execute as execute_sync

        args = DummyArgs(rebuild=False, source="github")
        execute_sync(args)

        mock_init_db.assert_called_once()
        mock_sync_github.assert_called_once()
        mock_run_reindexing.assert_called_once()
        mock_graph_inst.extract_and_sync_graph.assert_called_once()

    @patch("cli.commands.ask.init_db")
    @patch("cli.commands.ask.run_hybrid_rag")
    def test_ask_command(self, mock_run_hybrid_rag, mock_init_db):
        """Test memory-os ask command query execution."""
        mock_run_hybrid_rag.return_value = {
            "answer": "Python is used in core services.",
            "sources": ["source_1.txt"],
            "repositories": ["repo-a"],
            "confidence": 0.95
        }

        from cli.commands.ask import execute as execute_ask

        args = DummyArgs(question=["What", "projects", "use", "Python?"])
        execute_ask(args)

        mock_init_db.assert_called_once()
        mock_run_hybrid_rag.assert_called_once_with("What projects use Python?")

    @patch("storage.db.init_db")
    @patch("core.embedder.Embedder")
    @patch("cli.main.input")
    @patch("cli.commands.ask.run_and_print_ask")
    def test_interactive_repl_ask(self, mock_run_and_print_ask, mock_input, mock_embedder_class, mock_init_db):
        """Test interactive REPL triggers the ask command routing for natural language query."""
        # Mock REPL sequence: 1. A question, 2. 'exit' to terminate loop
        mock_input.side_effect = ["What projects use Python?", "exit"]
        
        # Mock embedder instantiation
        mock_embedder_inst = MagicMock()
        mock_embedder_class.return_value = mock_embedder_inst

        from cli.main import run_interactive

        with patch("core.vector_store.close_qdrant_client"), patch("storage.graph.GraphStore"):
            run_interactive()

        # Verify that natural language query gets routed to ask and calls run_and_print_ask
        mock_run_and_print_ask.assert_called_once_with("What projects use Python?")


if __name__ == "__main__":
    unittest.main()
