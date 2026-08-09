"""
Command: memory-os update

Checks and pulls updated Docker service images (Neo4j, Qdrant).
"""

from infrastructure.compose import ComposeManager


def execute(args):
    """Run the update command."""
    print("Checking and pulling latest Docker service images...")
    manager = ComposeManager()
    result = manager._run_cmd(["pull"])
    if result.returncode == 0:
        print("✓ Docker service images updated successfully.")
    else:
        print(f"⚠️ Failed to update images:\n{result.stderr}")
