"""
Command: memory-os restart

Restarts the Docker services (Neo4j and Qdrant) via ComposeManager.
"""

import sys
from infrastructure.compose import ComposeManager, wait_for_services


def execute(args):
    """Run the restart command."""
    print("Restarting Memory-OS local services (Neo4j, Qdrant)...")
    if not ComposeManager().restart():
        print("❌ Failed to restart docker compose services.")
        sys.exit(1)
        
    print("Waiting for services to become healthy...")
    if not wait_for_services(timeout=60):
        print("❌ Services failed to start or respond to health checks in time.")
        sys.exit(1)
        
    print("✓ Services restarted successfully and are healthy.")
