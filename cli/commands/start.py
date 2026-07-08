"""
Command: memory-os start

Starts the Docker services (Neo4j and Qdrant) via docker compose
and waits for them to become healthy.
"""

import sys
from infrastructure.compose import compose_up, wait_for_services


def execute(args):
    """Run the start command."""
    print("Starting Memory-OS local services (Neo4j, Qdrant)...")
    if not compose_up():
        print("❌ Failed to run docker compose up.")
        sys.exit(1)
        
    print("Waiting for services to become healthy...")
    if not wait_for_services(timeout=60):
        print("❌ Services failed to start or respond to health checks in time.")
        sys.exit(1)
        
    print("✓ Services started successfully and are healthy.")
