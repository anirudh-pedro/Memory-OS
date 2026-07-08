"""
Infrastructure: Docker Compose orchestration.

Wraps docker compose commands. Environment variables (ports, paths,
passwords) are exported by config.py before these functions are called,
so docker-compose.yml can reference them via ${VAR} syntax.
"""

import os
import subprocess
import time
import json
import logging

logger = logging.getLogger("infrastructure.compose")


def _get_compose_file() -> str:
    """Return path to the project's docker-compose.yml."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker-compose.yml")


def _run_compose(args: list[str], project_dir: str | None = None) -> subprocess.CompletedProcess:
    """Run a docker compose command with the project compose file."""
    from infrastructure.workspace import get_neo4j_path, get_qdrant_path

    compose_file = _get_compose_file()
    cmd = ["docker", "compose", "-f", compose_file] + args

    env = os.environ.copy()
    env["MEMORY_OS_NEO4J_PATH"] = str(get_neo4j_path())
    env["MEMORY_OS_QDRANT_PATH"] = str(get_qdrant_path())

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=project_dir,
    )



def compose_up(project_dir: str | None = None) -> bool:
    """Start services with docker compose up -d."""
    result = _run_compose(["up", "-d"], project_dir)
    if result.returncode != 0:
        logger.error(f"docker compose up failed: {result.stderr}")
        return False
    return True


def compose_down(project_dir: str | None = None) -> bool:
    """Stop and remove containers with docker compose down."""
    result = _run_compose(["down"], project_dir)
    if result.returncode != 0:
        logger.error(f"docker compose down failed: {result.stderr}")
        return False
    return True


def compose_stop(project_dir: str | None = None) -> bool:
    """Stop containers without removing them (preserves data)."""
    result = _run_compose(["stop"], project_dir)
    if result.returncode != 0:
        logger.error(f"docker compose stop failed: {result.stderr}")
        return False
    return True


def compose_status(project_dir: str | None = None) -> list[dict]:
    """Get container status via docker compose ps --format json."""
    result = _run_compose(["ps", "--format", "json"], project_dir)
    if result.returncode != 0:
        return []
    try:
        # docker compose ps --format json may return one JSON object per line
        containers = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                containers.append(json.loads(line))
        return containers
    except (json.JSONDecodeError, ValueError):
        return []


def wait_for_services(timeout: int = 60) -> bool:
    """Poll Neo4j and Qdrant health endpoints until ready or timeout.

    Returns True if all services are healthy within the timeout.
    """
    import urllib.request
    import urllib.error

    neo4j_port = os.getenv("NEO4J_HTTP_PORT", "7474")
    qdrant_port = os.getenv("QDRANT_PORT", "6333")

    neo4j_url = f"http://localhost:{neo4j_port}"
    qdrant_url = f"http://localhost:{qdrant_port}/healthz"

    start = time.time()
    neo4j_ready = False
    qdrant_ready = False

    while time.time() - start < timeout:
        # Check Qdrant
        if not qdrant_ready:
            try:
                req = urllib.request.urlopen(qdrant_url, timeout=3)
                if req.status == 200:
                    qdrant_ready = True
            except Exception:
                pass

        # Check Neo4j
        if not neo4j_ready:
            try:
                req = urllib.request.urlopen(neo4j_url, timeout=3)
                if req.status == 200:
                    neo4j_ready = True
            except Exception:
                pass

        if neo4j_ready and qdrant_ready:
            return True

        time.sleep(2)

    logger.warning(
        f"Service health timeout after {timeout}s. "
        f"Neo4j={'ready' if neo4j_ready else 'not ready'}, "
        f"Qdrant={'ready' if qdrant_ready else 'not ready'}"
    )
    return False
