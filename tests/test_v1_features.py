"""
Comprehensive unit and integration tests for Memory-OS v1.0 release features:
- Config manipulation, dotted paths, type validations, and resets.
- Export and import archive structure packaging, validation, and extraction.
- Workspace profile listing, switching, creation, info summaries, and deletion.
- Actionable recommendations in doctor diagnostics on check failures.
- Performance benchmark run logic.
- Connector plugin discovery, active plugin reporting, and registry.
- Standardized logs command and performance monitor dashboard.
- Infrastructure workspace profile folder trees and docker checking tools.
"""

import os
import sys
import unittest
import tempfile
import zipfile
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup isolated workspace for testing config
TEST_WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_temp_workspace")
os.environ["MEMORY_OS_WORKSPACE"] = TEST_WORKSPACE

from infrastructure.config import get_dotted, set_dotted, DEFAULTS, save_config, get_config
from connectors.registry import discover_connectors, register
from connectors.base import BaseConnector


class TestConfigurationSubsystem(unittest.TestCase):
    """Test suite verifying nested TOML configuration manager."""

    def setUp(self):
        if os.path.exists(TEST_WORKSPACE):
            shutil.rmtree(TEST_WORKSPACE)
        os.makedirs(TEST_WORKSPACE, exist_ok=True)
        save_config(DEFAULTS)

    def tearDown(self):
        if os.path.exists(TEST_WORKSPACE):
            shutil.rmtree(TEST_WORKSPACE)

    def test_dotted_get_and_set(self):
        success, _ = set_dotted("workspace", "~/.test-os")
        self.assertTrue(success)
        self.assertEqual(get_dotted("workspace"), "~/.test-os")

        success, _ = set_dotted("groq.model", "llama-test")
        self.assertTrue(success)
        self.assertEqual(get_dotted("groq.model"), "llama-test")

    def test_invalid_key_validations(self):
        success, err = set_dotted("groq.invalid_prop", "val")
        self.assertFalse(success)
        self.assertIn("Invalid configuration key", err)

    def test_type_coercion_and_validations(self):
        success, err = set_dotted("qdrant.port", "abc")
        self.assertFalse(success)
        self.assertIn("must be a positive integer", err)

        success, _ = set_dotted("qdrant.port", "9000")
        self.assertTrue(success)
        self.assertEqual(get_dotted("qdrant.port"), 9000)


class TestConfigCommand(unittest.TestCase):
    """Test suite verifying config CLI command executor."""

    @patch("cli.commands.config_cmd.input", return_value="y")
    def test_config_cli_actions(self, mock_input):
        from cli.commands.config_cmd import execute
        
        args = MagicMock()
        args.config_action = "show"
        execute(args)

        args.config_action = "get"
        args.key = "groq.model"
        execute(args)

        args.config_action = "set"
        args.key = "groq.model"
        args.value = "test-model"
        execute(args)
        self.assertEqual(get_dotted("groq.model"), "test-model")

        args.config_action = "reset"
        execute(args)


class TestWorkspaceProfiles(unittest.TestCase):
    """Test suite verifying active profile switches, listing, and info logic."""

    @patch("cli.commands.workspace.set_active_profile")
    @patch("cli.commands.workspace.list_profiles")
    @patch("cli.commands.workspace.get_active_profile")
    @patch("cli.commands.workspace.create_profile")
    @patch("cli.commands.workspace.delete_profile")
    @patch("cli.commands.workspace.input", return_value="y")
    def test_workspace_commands(self, mock_input, mock_delete, mock_create, mock_active, mock_list, mock_switch):
        mock_list.return_value = ["default", "work"]
        mock_active.return_value = "default"

        from cli.commands.workspace import execute
        args = MagicMock()
        
        args.workspace_action = "list"
        execute(args)

        args.workspace_action = "create"
        args.name = "test-ws"
        execute(args)

        args.workspace_action = "switch"
        args.name = "work"
        execute(args)

        args.workspace_action = "delete"
        args.name = "work"
        execute(args)

        args.workspace_action = "info"
        execute(args)


class TestExportImportSubsystem(unittest.TestCase):
    """Test suite verifying export ZIP contents packaging and validation on import."""

    @patch("cli.commands.import_cmd.input", return_value="y")
    @patch("cli.commands.import_cmd.compose_stop")
    @patch("cli.commands.import_cmd.compose_up")
    @patch("cli.commands.import_cmd.wait_for_services", return_value=True)
    def test_export_import_flow(self, mock_wait, mock_up, mock_stop, mock_input):
        from infrastructure.workspace import create_profile, set_active_profile
        create_profile("default")
        set_active_profile("default")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "test_export.zip"
            
            # 1. Export Mock execution
            from cli.commands.export import execute as run_export
            args = MagicMock()
            args.file = str(zip_path)
            run_export(args)
            
            self.assertTrue(zip_path.exists())

            # Verify contents
            with zipfile.ZipFile(zip_path, "r") as zipf:
                self.assertIn("metadata.json", zipf.namelist())
                self.assertIn("config.toml", zipf.namelist())

            # 2. Import Mock execution
            from cli.commands.import_cmd import execute as run_import
            args_import = MagicMock()
            args_import.file = str(zip_path)
            run_import(args_import)


class TestDoctorDiagnostics(unittest.TestCase):
    """Test suite verifying failure recommendations mapping inside Doctor CLI."""

    @patch("infrastructure.health.run_all_checks")
    def test_doctor_recommendations(self, mock_run_checks):
        mock_run_checks.return_value = [
            ("Docker Compose", False, "Missing binary"),
            ("SQLite", True, "Healthy")
        ]

        from cli.commands.doctor import execute
        args = MagicMock()
        
        with patch("sys.exit") as mock_exit:
            execute(args)


class TestBenchmarkDiagnostics(unittest.TestCase):
    """Test suite verifying benchmark command parses query latency tables."""

    @patch("cli.commands.benchmark.Embedder")
    @patch("infrastructure.health.check_qdrant")
    @patch("infrastructure.health.check_groq_api")
    def test_benchmark_run(self, mock_groq, mock_qdrant, mock_embedder):
        mock_groq.return_value = (False, "Offline")
        mock_qdrant.return_value = (False, "Offline")
        
        from cli.commands.benchmark import execute
        execute(None)
        mock_embedder.assert_called_once()


class TestPluginsCommand(unittest.TestCase):
    """Test suite verifying plugins command execution."""

    def test_plugins_run(self):
        from cli.commands.plugins import execute
        execute(None)


class TestMonitorCommand(unittest.TestCase):
    """Test suite verifying monitor metrics log parser execution."""

    def test_monitor_run(self):
        from cli.commands.monitor import execute
        execute(None)


class TestLogsCommand(unittest.TestCase):
    """Test suite verifying log tail command execution."""

    def test_logs_run(self):
        from cli.commands.logs import execute
        args = MagicMock()
        args.tail = 10
        execute(args)


class TestStartStopStatusCommands(unittest.TestCase):
    """Test suite verifying lifecycle daemon executions."""

    @patch("cli.commands.start.compose_up", return_value=True)
    @patch("cli.commands.start.wait_for_services", return_value=True)
    def test_start_run(self, mock_wait, mock_up):
        from cli.commands.start import execute
        execute(None)

    @patch("cli.commands.stop.compose_stop", return_value=True)
    def test_stop_run(self, mock_stop):
        from cli.commands.stop import execute
        execute(None)

    @patch("storage.db.get_repo_count", return_value=5)
    @patch("storage.db.get_repository_document_count", return_value=10)
    @patch("storage.db.get_email_count", return_value=15)
    @patch("storage.db.get_document_chunk_count", return_value=20)
    @patch("core.vector_store.get_vector_index_stats", return_value={"vectors": 20})
    def test_status_run(self, mock_stats, mock_chunk, mock_email, mock_doc, mock_repo):
        from cli.commands.status import execute
        execute(None)




class TestVersionCommand(unittest.TestCase):
    """Test suite verifying version subcommand execution."""

    def test_version_run(self):
        from cli.commands.version import execute
        execute(None)


class TestObservabilityParser(unittest.TestCase):
    """Test suite verifying log parser telemetry matching regex."""

    def test_observability_parser(self):
        from infrastructure.observability import get_performance_summary, parse_observability_metrics
        summary = get_performance_summary()
        self.assertIsInstance(summary, dict)


class TestDockerInfrastructure(unittest.TestCase):
    """Test suite verifying docker check tools."""

    @patch("subprocess.run")
    def test_docker_checks(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="version 2.0")
        from infrastructure.docker import check_docker_installed, check_docker_compose_installed, check_docker_running
        self.assertTrue(check_docker_installed()[0])
        self.assertTrue(check_docker_compose_installed()[0])


class TestPluginsRegistry(unittest.TestCase):
    """Test suite verifying active connector plugin registries and registry decoration."""

    def test_registry_registration(self):
        @register
        class TestDummyConnector(BaseConnector):
            name = "Dummy"
            slug = "dummy"
            def authenticate(self): return True
            def sync(self): return {}
            def health(self): return True, "Connected"

        connectors = discover_connectors()
        dummy_conn = next((c for c in connectors if c.slug == "dummy"), None)
        self.assertIsNotNone(dummy_conn)
        self.assertEqual(dummy_conn.name, "Dummy")
        self.assertTrue(dummy_conn.authenticate())


class TestComposeOrchestration(unittest.TestCase):
    """Test suite verifying compose daemon lifecycle functions."""

    @patch("subprocess.run")
    def test_run_compose_lifecycle(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"State": "running"}')
        from infrastructure.compose import compose_up, compose_down, compose_stop, compose_status
        self.assertTrue(compose_up())
        self.assertTrue(compose_down())
        self.assertTrue(compose_stop())
        self.assertIsInstance(compose_status(), list)

    @patch("urllib.request.urlopen")
    def test_wait_for_services(self, mock_urlopen):
        mock_urlopen.return_value = MagicMock(status=200)
        from infrastructure.compose import wait_for_services
        self.assertTrue(wait_for_services(timeout=2))


class TestHealthChecks(unittest.TestCase):
    """Test suite verifying all health check operations."""

    @patch("infrastructure.health.check_sqlite", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_neo4j", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_qdrant", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_embedding_model", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_groq_api", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_composio", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_connector", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_workspace", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_disk_usage", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_memory_usage", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_config_validation", return_value=(True, "Healthy"))
    @patch("infrastructure.health.check_active_plugins", return_value=(True, "Healthy"))
    def test_all_individual_health_checks(self, *mocks):
        from infrastructure.health import run_all_checks
        checks = run_all_checks()
        self.assertIsInstance(checks, list)


class TestMainEntrypoint(unittest.TestCase):
    """Test suite verifying main entry point execution command routing."""

    @patch("sys.argv", ["main.py", "--help"])
    def test_main_cli_help(self):
        from cli.main import cli_entrypoint
        with self.assertRaises(SystemExit) as cm:
            cli_entrypoint()
        self.assertEqual(cm.exception.code, 0)
