"""
CLI argument parser.

Builds the argparse parser with subcommands for all Memory-OS commands.
Each subcommand routes to its corresponding module in cli/commands/.
"""

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build and return the Memory-OS CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="memory-os",
        description="Memory-OS — CLI-based Personal Knowledge Operating System",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── init ──────────────────────────────────────────────────
    subparsers.add_parser(
        "init",
        help="Initialize Memory-OS (workspace, config, Docker services)",
    )

    # ── sync ──────────────────────────────────────────────────
    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync data from connected sources",
    )
    sync_parser.add_argument(
        "--rebuild", action="store_true",
        help="Full reset and rebuild from all sources",
    )
    sync_parser.add_argument(
        "--source", type=str, choices=["github", "gmail", "notion"],
        help="Sync only a specific source",
    )

    # ── ask ────────────────────────────────────────────────────
    ask_parser = subparsers.add_parser(
        "ask",
        help="Query the RAG pipeline with a question",
    )
    ask_parser.add_argument(
        "question", nargs="+", type=str,
        help="The question to ask",
    )

    # ── doctor ────────────────────────────────────────────────
    subparsers.add_parser(
        "doctor",
        help="Diagnose system health and connectivity",
    )

    # ── status ────────────────────────────────────────────────
    subparsers.add_parser(
        "status",
        help="Show workspace and service status",
    )

    # ── backup ────────────────────────────────────────────────
    backup_parser = subparsers.add_parser(
        "backup",
        help="Create a timestamped backup of workspace data",
    )
    backup_parser.add_argument(
        "--include-logs", action="store_true",
        help="Include log files in the backup",
    )

    # ── export ────────────────────────────────────────────────
    export_parser = subparsers.add_parser(
        "export",
        help="Export active workspace profile and configuration to a compressed file",
    )
    export_parser.add_argument(
        "file", type=str,
        help="Target archive file path (e.g. backup.zip)",
    )

    # ── import ────────────────────────────────────────────────
    import_parser = subparsers.add_parser(
        "import",
        help="Import and restore a previously exported workspace archive",
    )
    import_parser.add_argument(
        "file", type=str,
        help="Workspace archive file path to import",
    )


    # ── graph ─────────────────────────────────────────────────
    graph_parser = subparsers.add_parser(
        "graph",
        help="Show knowledge graph relationships for a repository",
    )
    graph_parser.add_argument(
        "repo", type=str,
        help="Repository name to inspect",
    )

    # ── update ────────────────────────────────────────────────
    subparsers.add_parser(
        "update",
        help="Check and update Docker service images",
    )

    # ── start ─────────────────────────────────────────────────
    subparsers.add_parser(
        "start",
        help="Start Docker services (Neo4j, Qdrant)",
    )

    # ── stop ──────────────────────────────────────────────────
    subparsers.add_parser(
        "stop",
        help="Stop Docker services (preserves data)",
    )

    # ── version ───────────────────────────────────────────────
    subparsers.add_parser(
        "version",
        help="Show Memory-OS version information",
    )

    # ── logs ──────────────────────────────────────────────────
    logs_parser = subparsers.add_parser(
        "logs",
        help="View Memory-OS log output",
    )
    logs_parser.add_argument(
        "--tail", type=int, default=50,
        help="Number of log lines to show (default: 50)",
    )

    # ── migrate ───────────────────────────────────────────────
    subparsers.add_parser(
        "migrate",
        help="Migrate existing data into the workspace",
    )

    # ── workspace ─────────────────────────────────────────────
    workspace_parser = subparsers.add_parser(
        "workspace",
        help="Manage workspace profiles",
    )
    workspace_sub = workspace_parser.add_subparsers(dest="workspace_action")
    ws_create = workspace_sub.add_parser("create", help="Create a new workspace profile")
    ws_create.add_argument("name", type=str, help="Profile name")
    ws_switch = workspace_sub.add_parser("switch", help="Switch active workspace profile")
    ws_switch.add_argument("name", type=str, help="Profile name to switch to")
    workspace_sub.add_parser("list", help="List all workspace profiles")
    ws_delete = workspace_sub.add_parser("delete", help="Delete a workspace profile")
    ws_delete.add_argument("name", type=str, help="Profile name to delete")

    # ── config ────────────────────────────────────────────────
    config_parser = subparsers.add_parser(
        "config",
        help="Inspect or modify configuration",
    )
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Show full configuration")
    config_get = config_sub.add_parser("get", help="Get a config value")
    config_get.add_argument("key", type=str, help="Config key (e.g. groq.model)")
    config_set = config_sub.add_parser("set", help="Set a config value")
    config_set.add_argument("key", type=str, help="Config key (e.g. groq.model)")
    config_set.add_argument("value", type=str, help="New value")

    # ── plugins ───────────────────────────────────────────────
    subparsers.add_parser(
        "plugins",
        help="List installed and available connector plugins",
    )

    # ── monitor ───────────────────────────────────────────────
    subparsers.add_parser(
        "monitor",
        help="Show system observability and latency performance metrics",
    )

    # ── benchmark ─────────────────────────────────────────────
    subparsers.add_parser(
        "benchmark",
        help="Perform speed run latency benchmarks on query pipelines",
    )

    return parser
