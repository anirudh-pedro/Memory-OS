"""
Memory-OS — Compatibility wrapper.

Delegates to the cli package. Preserves ``python main.py`` for
existing users while the canonical entry point is ``memory-os``.
"""

from cli.main import cli_entrypoint

if __name__ == "__main__":
    cli_entrypoint()
