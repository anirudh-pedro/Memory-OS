"""
Integration tests for Memory-OS CLI entry points.

These are the "must-pass" regression tests before every release.
They verify that all CLI entry points resolve, parse arguments
correctly, and produce expected output without crashing.

Run with:
    uv run pytest tests/test_cli_integration.py -v
"""

import subprocess
import sys
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a CLI command via ``uv run`` and return the CompletedProcess."""
    cmd = [sys.executable, "-m", "cli.main", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


# ─── Entry Point Tests ───────────────────────────────────────────


class TestCLIHelp:
    """memory-os --help must always work."""

    def test_help_exits_zero(self):
        result = run_cli("--help")
        assert result.returncode == 0

    def test_help_shows_description(self):
        result = run_cli("--help")
        assert "Memory-OS" in result.stdout

    def test_help_lists_subcommands(self):
        result = run_cli("--help")
        expected_commands = [
            "init", "sync", "ask", "doctor", "status",
            "backup", "graph", "update", "start", "stop",
            "version", "logs", "migrate", "workspace", "config",
        ]
        for cmd in expected_commands:
            assert cmd in result.stdout, f"Subcommand '{cmd}' missing from --help output"


class TestMainPyCompat:
    """python main.py must remain a working entry point."""

    def test_main_py_help(self):
        result = subprocess.run(
            [sys.executable, "main.py", "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 0
        assert "Memory-OS" in result.stdout

    def test_main_py_version(self):
        result = subprocess.run(
            [sys.executable, "main.py", "version"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 0
        assert "Memory-OS" in result.stdout


class TestModuleExecution:
    """python -m cli.main must work."""

    def test_module_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "cli.main", "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 0
        assert "Memory-OS" in result.stdout


# ─── Subcommand Tests ─────────────────────────────────────────────


class TestVersionCommand:
    """memory-os version must report version info."""

    def test_exits_zero(self):
        result = run_cli("version")
        assert result.returncode == 0

    def test_shows_memory_os_version(self):
        result = run_cli("version")
        assert "Memory-OS" in result.stdout

    def test_shows_python_version(self):
        result = run_cli("version")
        assert "Python" in result.stdout

    def test_shows_docker_line(self):
        result = run_cli("version")
        assert "Docker" in result.stdout


class TestStatusCommand:
    """memory-os status must report database stats without crashing."""

    def test_exits_zero(self):
        result = run_cli("status")
        assert result.returncode == 0

    def test_shows_repositories(self):
        result = run_cli("status")
        assert "Repositories" in result.stdout

    def test_shows_documents(self):
        result = run_cli("status")
        assert "Documents" in result.stdout

    def test_shows_emails(self):
        result = run_cli("status")
        assert "Emails" in result.stdout

    def test_shows_vectors(self):
        result = run_cli("status")
        assert "Vectors" in result.stdout

    def test_shows_embedding_model(self):
        result = run_cli("status")
        assert "Embedding Model" in result.stdout


# ─── Subcommand Help Tests ────────────────────────────────────────


class TestSubcommandHelp:
    """Every subcommand must respond to --help without crashing."""

    @pytest.mark.parametrize("subcommand", [
        "init", "sync", "ask", "doctor", "status",
        "backup", "graph", "update", "start", "stop",
        "version", "logs", "migrate", "workspace", "config",
    ])
    def test_subcommand_help(self, subcommand):
        result = run_cli(subcommand, "--help")
        assert result.returncode == 0, (
            f"'{subcommand} --help' failed with:\n{result.stderr}"
        )


# ─── Module Import Tests ─────────────────────────────────────────


class TestModuleImports:
    """All new packages must import without errors."""

    def test_import_cli_parser(self):
        from cli.parser import build_parser
        parser = build_parser()
        assert parser is not None

    def test_import_cli_main(self):
        from cli.main import cli_entrypoint
        assert callable(cli_entrypoint)

    def test_import_infrastructure_config(self):
        from infrastructure.config import load_config, DEFAULTS
        assert isinstance(DEFAULTS, dict)

    def test_import_infrastructure_workspace(self):
        from infrastructure.workspace import get_workspace_root
        assert callable(get_workspace_root)

    def test_import_infrastructure_docker(self):
        from infrastructure.docker import check_docker_installed
        assert callable(check_docker_installed)

    def test_import_infrastructure_compose(self):
        from infrastructure.compose import compose_up
        assert callable(compose_up)

    def test_import_infrastructure_health(self):
        from infrastructure.health import run_all_checks
        assert callable(run_all_checks)

    def test_import_connectors_base(self):
        from connectors.base import BaseConnector
        assert BaseConnector is not None

    def test_import_connectors_registry(self):
        from connectors.registry import discover_connectors
        assert callable(discover_connectors)


# ─── Parser Unit Tests ────────────────────────────────────────────


class TestParserRouting:
    """Argparse must correctly parse subcommands and flags."""

    def test_parse_version(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["version"])
        assert args.command == "version"

    def test_parse_status(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["status"])
        assert args.command == "status"

    def test_parse_sync_rebuild(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["sync", "--rebuild"])
        assert args.command == "sync"
        assert args.rebuild is True

    def test_parse_sync_source(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["sync", "--source", "github"])
        assert args.command == "sync"
        assert args.source == "github"

    def test_parse_ask(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["ask", "What", "is", "LangChain?"])
        assert args.command == "ask"
        assert args.question == ["What", "is", "LangChain?"]

    def test_parse_graph(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["graph", "my-repo"])
        assert args.command == "graph"
        assert args.repo == "my-repo"

    def test_parse_logs_tail(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["logs", "--tail", "100"])
        assert args.command == "logs"
        assert args.tail == 100

    def test_parse_workspace_create(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["workspace", "create", "work"])
        assert args.command == "workspace"
        assert args.workspace_action == "create"
        assert args.name == "work"

    def test_parse_config_set(self):
        from cli.parser import build_parser
        args = build_parser().parse_args(["config", "set", "groq.model", "llama-3.3-70b-versatile"])
        assert args.command == "config"
        assert args.config_action == "set"
        assert args.key == "groq.model"
        assert args.value == "llama-3.3-70b-versatile"

    def test_parse_no_command(self):
        from cli.parser import build_parser
        args = build_parser().parse_args([])
        assert args.command is None
