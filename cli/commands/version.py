"""
Command: memory-os version

Shows Memory-OS version, Python version, and Docker version.
"""

import sys


def execute(args):
    """Run the version command."""
    from infrastructure.docker import check_docker_installed
    from infrastructure.health import _get_version

    version = _get_version()
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    docker_available, docker_version = check_docker_installed()

    print(f"Memory-OS  {version}")
    print(f"Python     {python_version}")
    if docker_available:
        print(f"Docker     {docker_version}")
    else:
        print("Docker     not installed")
