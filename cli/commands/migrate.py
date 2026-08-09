"""
Command: memory-os migrate

Runs database schema and workspace data migrations.
"""

from storage.db import init_db


def execute(args):
    """Run the migrate command."""
    print("Running database migrations...")
    try:
        init_db()
        print("✓ Database schema and migrations up to date.")
    except Exception as e:
        print(f"❌ Migration failed: {e}")
