"""
Infrastructure: Service health checks.

Individual check functions for Neo4j, Qdrant, SQLite, Groq, Composio,
embedding model, and connectors. Used by the ``doctor`` command.
"""

import os
import sys
import logging

logger = logging.getLogger("infrastructure.health")


def check_python() -> tuple[bool, str]:
    """Check Python version."""
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 12)
    return ok, version


def check_docker() -> tuple[bool, str]:
    """Verify Docker daemon availability."""
    from infrastructure.docker import check_docker_daemon
    return check_docker_daemon()


def check_neo4j() -> tuple[bool, str]:
    """Attempt a Neo4j bolt connection."""
    try:
        from neo4j import GraphDatabase
        from neo4j.exceptions import AuthError
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
            driver.close()
            return True, "Healthy"
        except AuthError as ae:
            try:
                driver.close()
            except Exception:
                pass
            return False, f"Authentication failed: {ae}"
        except Exception as e:
            try:
                driver.close()
            except Exception:
                pass
            return False, f"Unreachable: {e}"
    except Exception as e:
        return False, str(e)


def check_qdrant() -> tuple[bool, str]:
    """Ping the Qdrant HTTP health endpoint and check version compatibility."""
    import urllib.request
    import json
    try:
        from importlib.metadata import version
        client_ver = version("qdrant-client")
    except Exception:
        client_ver = "1.18.0"

    port = os.getenv("QDRANT_PORT", "6333")
    url = f"http://localhost:{port}"
    try:
        req = urllib.request.urlopen(url, timeout=5)
        if req.status == 200:
            data = json.loads(req.read().decode("utf-8"))
            server_ver = data.get("version", "unknown")
            c_parts = client_ver.split(".")[:2]
            s_parts = server_ver.split(".")[:2]
            if c_parts == s_parts:
                return True, "Qdrant version compatible"
            else:
                return False, f"Qdrant running, but version mismatch (Client: {client_ver}, Server: {server_ver})"
        return False, f"HTTP {req.status}"
    except Exception as e:
        return False, f"Unreachable: {e}"


def check_sqlite(db_path: str | None = None) -> tuple[bool, str]:
    """Verify a SQLite database file is valid."""
    import sqlite3
    if db_path is None:
        db_path = os.getenv("MEMORY_OS_DB_PATH", "memory.db")
    if not os.path.exists(db_path):
        return False, f"File not found: {db_path}"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()
        if result and result[0] == "ok":
            return True, "Healthy"
        return False, f"Integrity check: {result}"
    except Exception as e:
        return False, str(e)


def check_groq() -> tuple[bool, str]:
    """Make a minimal Groq API test call."""
    try:
        from groq import Groq
        key = os.getenv("GROQ_API_KEY")
        if not key:
            return False, "No API key"
        client = Groq(api_key=key)
        client.models.list()
        return True, "Connected"
    except Exception as e:
        return False, str(e)


def check_groq_api() -> tuple[bool, str]:
    """Make a minimal Groq API test call (legacy wrapper)."""
    return check_groq()


def check_composio() -> tuple[bool, str]:
    """Verify Composio toolkit status."""
    try:
        from composio import Composio
        c = Composio()
        s = c.create(user_id=os.getenv("COMPOSIO_USER_ID", "user_123"))
        toolkits = s.toolkits()
        count = len(toolkits.items) if toolkits and toolkits.items else 0
        return True, f"Connected ({count} toolkits)"
    except Exception as e:
        return False, str(e)



def check_embedding_model() -> tuple[bool, str]:
    """Check if the sentence-transformers model is cached locally."""
    try:
        from sentence_transformers import SentenceTransformer
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        # Try loading from cache only
        SentenceTransformer(model_name, local_files_only=True)
        return True, model_name
    except Exception:
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        return False, f"{model_name} (not cached)"


def check_connector(name: str) -> tuple[bool, str]:
    """Check if a Composio connector (github, gmail, notion) is active."""
    try:
        from composio import Composio
        c = Composio()
        s = c.create(user_id=os.getenv("COMPOSIO_USER_ID", "user_123"))
        toolkits = s.toolkits()
        tk = next((t for t in toolkits.items if t.slug == name), None)
        if tk and tk.connection and tk.connection.is_active:
            return True, "Connected"
        return False, "Not connected"
    except Exception as e:
        return False, str(e)


def check_workspace() -> tuple[bool, str]:
    """Check if the workspace directory exists and is writable."""
    from infrastructure.workspace import get_workspace_root
    root = get_workspace_root()
    if not root.exists():
        return False, "Not initialized"
    # Check writable
    test_file = root / ".write_test"
    try:
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        return True, str(root)
    except Exception as e:
        return False, f"Not writable: {e}"


def check_disk_usage() -> tuple[bool, str]:
    """Calculate workspace disk usage."""
    from infrastructure.workspace import get_workspace_root, get_workspace_size
    root = get_workspace_root()
    if not root.exists():
        return False, "Workspace not found"
    size_bytes = get_workspace_size()
    if size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.0f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        size_str = f"{size_bytes / (1024 * 1024):.0f} MB"
    else:
        size_str = f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    return True, size_str


def check_memory_usage() -> tuple[bool, str]:
    """Report current process memory usage."""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem = process.memory_info().rss
        if mem < 1024 * 1024:
            return True, f"{mem / 1024:.0f} KB"
        return True, f"{mem / (1024 * 1024):.0f} MB"
    except ImportError:
        # psutil not available, use a rough estimate
        return True, "N/A (psutil not installed)"
    except Exception as e:
        return False, str(e)


def check_config_validation() -> tuple[bool, str]:
    """Verify configuration validation."""
    from infrastructure.config import get_config, DEFAULTS
    try:
        config = get_config()
        for key in DEFAULTS:
            if key not in config:
                return False, f"Missing section '{key}'"
            if isinstance(DEFAULTS[key], dict):
                if not isinstance(config[key], dict):
                    return False, f"Section '{key}' must be a dictionary"
                for subkey in DEFAULTS[key]:
                    if subkey not in config[key]:
                        return False, f"Missing subkey '{key}.{subkey}'"
        return True, "Valid"
    except Exception as e:
        return False, str(e)


def check_active_plugins() -> tuple[bool, str]:
    """Verify connector plugins registration and connection status."""
    try:
        from connectors.registry import discover_connectors
        active = []
        for conn in discover_connectors():
            if conn.authenticate():
                active.append(conn.name)
        if active:
            return True, f"{len(active)} active ({', '.join(active)})"
        return False, "0 active"
    except Exception as e:
        return False, str(e)


def run_all_checks() -> list[tuple[str, bool, str]]:
    """Run all health checks and return a list of (name, passed, detail)."""
    from infrastructure.docker import check_docker_installed, check_docker_compose_installed

    checks = []

    # Python
    ok, detail = check_python()
    checks.append(("Python", ok, detail))

    # Docker
    ok, detail = check_docker()
    checks.append(("Docker", ok, detail))

    # Docker Compose
    ok, detail = check_docker_compose_installed()
    checks.append(("Docker Compose", ok, detail))

    # SQLite
    ok, detail = check_sqlite()
    checks.append(("SQLite", ok, detail))

    # Neo4j
    ok, detail = check_neo4j()
    checks.append(("Neo4j", ok, detail))

    # Qdrant
    ok, detail = check_qdrant()
    checks.append(("Qdrant", ok, detail))

    # Embedding Model
    ok, detail = check_embedding_model()
    checks.append(("Embedding Model", ok, detail))

    # Groq
    ok, detail = check_groq()
    checks.append(("Groq", ok, detail))

    # Composio
    ok, detail = check_composio()
    checks.append(("Composio", ok, detail))

    # Config Validation
    ok, detail = check_config_validation()
    checks.append(("Config Validation", ok, detail))

    # Active Plugins
    ok, detail = check_active_plugins()
    checks.append(("Active Plugins", ok, detail))

    # Connectors
    for name in ["github", "gmail", "notion"]:
        ok, detail = check_connector(name)
        checks.append((name.capitalize(), ok, detail))

    # Workspace
    ok, detail = check_workspace()
    checks.append(("Workspace", ok, detail))

    # Disk Usage
    ok, detail = check_disk_usage()
    checks.append(("Disk Usage", ok, detail))

    # Memory Usage
    ok, detail = check_memory_usage()
    checks.append(("Memory Usage", ok, detail))

    # Version
    checks.append(("Version", True, _get_version()))

    # Workspace Profile & Database Counts
    try:
        from infrastructure.workspace import get_active_profile
        checks.append(("Workspace Profile", True, get_active_profile()))
    except Exception:
        pass

    try:
        from core.vector_store import get_vector_index_stats
        vectors = get_vector_index_stats().get("vectors", 0)
        checks.append(("Vector Count", True, f"{vectors:,}"))
    except Exception:
        checks.append(("Vector Count", True, "0"))

    try:
        from storage.db import get_repo_count, get_email_count
        repos = get_repo_count()
        emails = get_email_count()
        checks.append(("Repositories", True, str(repos)))
        checks.append(("Emails", True, str(emails)))
    except Exception:
        checks.append(("Repositories", True, "0"))
        checks.append(("Emails", True, "0"))

    try:
        from storage.graph import GraphStore
        nodes = 0
        rels = 0
        graph = GraphStore()
        if graph.is_fallback:
            from storage.db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM graph_nodes")
            nodes = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM graph_relationships")
            rels = cursor.fetchone()[0]
            conn.close()
        else:
            with graph.driver.session() as session:
                r_nodes = session.run("MATCH (n) RETURN count(n) AS c")
                nodes = r_nodes.single()["c"]
                r_rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
                rels = r_rels.single()["c"]
        checks.append(("Graph Nodes", True, str(nodes)))
        checks.append(("Graph Relationships", True, str(rels)))
    except Exception:
        checks.append(("Graph Nodes", True, "0"))
        checks.append(("Graph Relationships", True, "0"))

    return checks


def _get_version() -> str:
    """Get the Memory-OS package version."""
    try:
        from importlib.metadata import version
        return version("memory-os")
    except Exception:
        return "0.1.0"
