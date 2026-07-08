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


def check_docker_running() -> bool:
    """Verify that the Docker daemon is active."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.error(f"Docker daemon check failed: {e}")
        return False
