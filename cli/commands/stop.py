"""
Command: memory-os stop

Stops the Docker services (Neo4j and Qdrant) via docker compose stop.
Keeps data volumes intact.
"""

import sys
from infrastructure.compose import compose_stop


def execute(args):
    """Run the stop command."""
    print("Stopping Memory-OS local services (Neo4j, Qdrant)...")
    if not compose_stop():
        print("❌ Failed to run docker compose stop.")
        sys.exit(1)
        
    print("✓ Services stopped successfully. Data remains intact.")
