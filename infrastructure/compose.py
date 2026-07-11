"""
Infrastructure: Docker Compose orchestration via ComposeManager.

Manages dynamic template rendering, validation, and container operations
without relying on the current working directory.
"""

import os
import subprocess
import time
import json
import logging
from pathlib import Path

logger = logging.getLogger("infrastructure.compose")


class ComposeManager:
    """Manages Docker Compose services for Memory-OS workspaces."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        """Initialize ComposeManager with a workspace root."""
        if workspace_root is None:
            from infrastructure.workspace import get_workspace_root
            self.workspace_root = get_workspace_root()
        else:
            self.workspace_root = Path(workspace_root)

    def get_compose_path(self) -> Path:
        """Return the path to the docker-compose.yml file."""
        return self.workspace_root / "docker-compose.yml"

    def generate_compose(self, profile: str | None = None, password: str | None = None) -> None:
        """Generate docker-compose.yml dynamically from a Python template."""
        from infrastructure.workspace import get_active_profile, get_neo4j_path, get_qdrant_path
        from infrastructure.config import get_config

        if profile is None:
            profile = get_active_profile()

        # Load values from config
        config = get_config()
        neo4j_config = config.get("neo4j", {})
        qdrant_config = config.get("qdrant", {})

        # Resolve password
        if password is None:
            password = neo4j_config.get("password") or "memory_neo"

        neo4j_http_port = neo4j_config.get("port_http", 7474)
        neo4j_bolt_port = neo4j_config.get("port_bolt", 7687)
        qdrant_port_6333 = qdrant_config.get("port", 6333)
        qdrant_port_6334 = 6334 if qdrant_port_6333 == 6333 else qdrant_port_6333 + 1

        # Paths should be posix format for cross-platform Docker mount compatibility
        neo4j_vol = get_neo4j_path(profile).resolve().as_posix()
        qdrant_vol = get_qdrant_path(profile).resolve().as_posix()

        # Ensure volume directories exist
        Path(neo4j_vol).mkdir(parents=True, exist_ok=True)
        Path(qdrant_vol).mkdir(parents=True, exist_ok=True)

        content = f"""services:
  neo4j:
    image: neo4j:5
    container_name: memory-os-neo4j-{profile}
    ports:
      - "{neo4j_http_port}:7474"
      - "{neo4j_bolt_port}:7687"
    environment:
      - NEO4J_AUTH=neo4j/{password}
    volumes:
      - "{neo4j_vol}:/data"
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:v1.18.0
    container_name: memory-os-qdrant-{profile}
    ports:
      - "{qdrant_port_6333}:6333"
      - "{qdrant_port_6334}:6334"
    volumes:
      - "{qdrant_vol}:/qdrant/storage"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:6333/healthz || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
"""
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.get_compose_path().write_text(content, encoding="utf-8")
        logger.info(f"Generated docker-compose.yml at {self.get_compose_path()} for profile '{profile}'")

    def validate(self, profile: str | None = None) -> None:
        """Validate compose file existence, YAML parsing, and workspace dirs."""
        from infrastructure.workspace import get_active_profile, ensure_workspace, get_neo4j_path, get_qdrant_path
        if profile is None:
            profile = get_active_profile()

        ensure_workspace(profile)
        get_neo4j_path(profile).mkdir(parents=True, exist_ok=True)
        get_qdrant_path(profile).mkdir(parents=True, exist_ok=True)

        compose_path = self.get_compose_path()
        if not compose_path.exists():
            self.generate_compose(profile)

        # Validate YAML parsing
        import yaml
        try:
            with open(compose_path, "r", encoding="utf-8") as f:
                yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Corrupted or invalid docker-compose.yml: {e}. Regenerating...")
            self.generate_compose(profile)

    def _run_cmd(self, args: list[str]) -> subprocess.CompletedProcess:
        """Execute a docker compose command against the generated file."""
        compose_path = self.get_compose_path()
        cmd = ["docker", "compose", "-f", str(compose_path)] + args
        env = os.environ.copy()

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

    def _handle_failure(self, result: subprocess.CompletedProcess, recommendation: str) -> None:
        """Format and print standard, actionable diagnostics for compose failures."""
        print("Docker command:")
        print(" ".join(result.args))
        print("")
        print("Exit code:")
        print(result.returncode)
        print("")
        print("stdout:")
        print(result.stdout or "")
        print("")
        print("stderr:")
        print(result.stderr or "")
        print("")
        print("Recommendation:")
        print(recommendation)

    def up(self, profile: str | None = None) -> bool:
        """Start services using docker compose up -d."""
        self.validate(profile)
        result = self._run_cmd(["up", "-d"])
        if result.returncode != 0:
            logger.error(f"docker compose up failed: {result.stderr}")
            self._handle_failure(
                result=result,
                recommendation="Run:\n  memory-os doctor\nor\n  docker compose -f " + str(self.get_compose_path()) + " logs"
            )
            return False
        return True

    def down(self, profile: str | None = None) -> bool:
        """Stop and remove services using docker compose down."""
        self.validate(profile)
        result = self._run_cmd(["down"])
        if result.returncode != 0:
            logger.error(f"docker compose down failed: {result.stderr}")
            self._handle_failure(
                result=result,
                recommendation="Run:\n  docker compose -f " + str(self.get_compose_path()) + " down"
            )
            return False
        return True

    def stop(self, profile: str | None = None) -> bool:
        """Stop services using docker compose stop."""
        self.validate(profile)
        result = self._run_cmd(["stop"])
        if result.returncode != 0:
            logger.error(f"docker compose stop failed: {result.stderr}")
            self._handle_failure(
                result=result,
                recommendation="Run:\n  docker compose -f " + str(self.get_compose_path()) + " stop"
            )
            return False
        return True

    def restart(self, profile: str | None = None) -> bool:
        """Restart services using docker compose restart."""
        self.validate(profile)
        result = self._run_cmd(["restart"])
        if result.returncode != 0:
            logger.error(f"docker compose restart failed: {result.stderr}")
            self._handle_failure(
                result=result,
                recommendation="Run:\n  docker compose -f " + str(self.get_compose_path()) + " restart"
            )
            return False
        return True

    def status(self, profile: str | None = None) -> list[dict]:
        """Get container status using docker compose ps --format json."""
        self.validate(profile)
        result = self._run_cmd(["ps", "--format", "json"])
        if result.returncode != 0:
            return []
        try:
            containers = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    containers.append(json.loads(line))
            return containers
        except (json.JSONDecodeError, ValueError):
            return []


# ── Backward Compatibility Helpers ────────────────────────


def format_infra_failure(cmd: list[str], exit_code: int, stderr: str, recommendation: str) -> None:
    """Print standard, actionable docker/infrastructure command failure report."""
    print("Docker command:")
    print(" ".join(cmd))
    print("")
    print("Exit code:")
    print(exit_code)
    print("")
    print("stderr:")
    print(stderr)
    print("")
    print("Recommendation:")
    print(recommendation)


def compose_up(project_dir: str | None = None) -> bool:
    """Start services (legacy wrapper)."""
    return ComposeManager().up()


def compose_down(project_dir: str | None = None) -> bool:
    """Stop and remove services (legacy wrapper)."""
    return ComposeManager().down()


def compose_stop(project_dir: str | None = None) -> bool:
    """Stop services (legacy wrapper)."""
    return ComposeManager().stop()


def compose_status(project_dir: str | None = None) -> list[dict]:
    """Get container status (legacy wrapper)."""
    return ComposeManager().status()


def wait_for_services(timeout: int = 60) -> bool:
    """Poll Neo4j and Qdrant health endpoints until ready or timeout."""
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
