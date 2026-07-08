"""
Command: memory-os logs [--tail N]

Tails the active log file to inspect system traces, errors, and indexing events.
"""

from pathlib import Path
from infrastructure.workspace import get_logs_path


def execute(args):
    """Run the logs command."""
    tail_count = args.tail
    
    # Resolve log file path
    try:
        log_file = get_logs_path() / "memory_os.log"
    except Exception:
        log_file = Path("logs/memory_os.log")

    if not log_file.exists():
        print(f"No log file found at '{log_file.resolve()}'. Run commands to generate logs.")
        return

    print(f"─────────────────────────────")
    print(f"  Memory-OS Log Tail (Last {tail_count} lines)")
    print(f"  File: {log_file.resolve()}")
    print(f"─────────────────────────────")

    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            tail_lines = lines[-tail_count:]
            for line in tail_lines:
                print(line.rstrip())
    except Exception as e:
        print(f"❌ Failed to read log file: {e}")
    print(f"─────────────────────────────")
