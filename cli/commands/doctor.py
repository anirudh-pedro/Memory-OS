"""
Command: memory-os doctor

Diagnoses system health and connectivity across all services.
"""


def execute(args):
    """Run the doctor command."""
    from storage.db import init_db
    try:
        init_db()
    except Exception:
        pass

    from infrastructure.health import run_all_checks

    print("─────────────────────────────")
    print("  memory-os doctor")
    print("─────────────────────────────")

    checks = run_all_checks()

    max_name_len = max(len(name) for name, _, _ in checks)

    for name, passed, detail in checks:
        icon = "✓" if passed else "✗"
        padding = " " * (max_name_len - len(name) + 2)
        print(f"  {name}{padding}{icon} {detail}")

    print("─────────────────────────────")

    failed = [(name, detail) for name, passed, detail in checks if not passed]
    if failed:
        print(f"\n  {len(failed)} issue(s) detected.")
        print("\n─────────────────────────────")
        print("  Actionable Recommendations")
        print("─────────────────────────────")
        recommendations = {
            "Docker": "Install Docker Desktop from https://www.docker.com/",
            "Docker Compose": "Ensure Docker Compose is installed ('docker compose version').",
            "Neo4j": "Run:\n  memory-os start",
            "Qdrant": "Run:\n  memory-os start",
            "Groq": "memory-os config set groq.api_key <key>",
            "Composio": "memory-os config set composio.api_key <key>",
            "SQLite": "Workspace not initialized. Run memory-os init.",
            "Github": "Authenticate GitHub connector: run 'memory-os init'",
            "Gmail": "Authenticate Gmail connector: run 'memory-os init'",
            "Notion": "Authenticate Notion connector: run 'memory-os init'",
            "Workspace": "Workspace not initialized.\nRun: memory-os init",
            "Embedding Model": "Download embedding model: run 'memory-os init'",
            "Config Validation": "Reset config.toml file: run 'memory-os config reset'",
            "Active Plugins": "No plugins are authenticated. Run 'memory-os init' to set up connector logins.",
        }
        for name, detail in failed:
            rec = recommendations.get(name, "Check log file logs/memory_os.log for errors.")
            print(f"  * {name}: {rec} (Detail: {detail})")
        print("─────────────────────────────")
    else:
        print("\n  All checks passed.")

