"""
Command: memory-os restore <file>

Safely unpacks and restores a previously exported workspace archive
into the active workspace profile (alias for memory-os import).
"""

from cli.commands.import_cmd import execute

__all__ = ["execute"]
