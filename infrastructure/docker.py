"""
Infrastructure: Docker availability checks.

Verifies that Docker and Docker Compose are installed and running.
"""

import subprocess
import logging

logger = logging.getLogger("infrastructure.docker")


def check_docker_installed() -> tuple[bool, str]:
    """Check if Docker is installed. Returns (available, version_string)."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, ""
    except FileNotFoundError:
        return False, ""
    except Exception as e:
        logger.error(f"Docker check failed: {e}")
        return False, ""


def check_docker_compose_installed() -> tuple[bool, str]:
    """Check if Docker Compose is installed. Returns (available, version_string)."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, ""
    except FileNotFoundError:
        return False, ""
    except Exception as e:
        logger.error(f"Docker Compose check failed: {e}")
        return False, ""


def check_docker_daemon() -> tuple[bool, str]:
    """Verify that the Docker daemon is active by running 'docker info'.
    
    Returns (available, version_string_or_stderr).
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import re
            m = re.search(r"Server Version:\s*([^\n]+)", result.stdout)
            version = m.group(1).strip() if m else "Running"
            return True, version
        else:
            stderr = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
            if not stderr and result.stdout:
                stderr = result.stdout.strip()
            return False, stderr
    except FileNotFoundError:
        return False, "Docker is not installed or not in PATH."
    except Exception as e:
        logger.error(f"Docker daemon check failed: {e}")
        return False, str(e)


def check_docker_running() -> bool:
    """Verify that the Docker daemon is active (legacy wrapper)."""
    ok, _ = check_docker_daemon()
    return ok

