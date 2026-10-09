"""
Command: memory-os config show|get|set|reset

Enables querying and modification of key-value configuration pairs.
"""

import sys
from infrastructure.config import (
    get_config,
    get_dotted,
    set_dotted,
    save_config,
    DEFAULTS
)


def _mask_val(key_name: str, val):
    if not isinstance(val, str) or not val:
        return val
    lower_k = key_name.lower()
    if any(s in lower_k for s in ["api_key", "password", "token", "secret"]):
        if len(val) > 8:
            return val[:4] + "*" * (len(val) - 8) + val[-4:]
        return "********"
    return val


def execute(args):
    """Run the config command."""
    action = getattr(args, "config_action", None)

    if action == "show":
        config = get_config()
        print("─────────────────────────────")
        print("  Memory-OS Configuration")
        print("─────────────────────────────")
        for key, val in config.items():
            if isinstance(val, dict):
                print(f"[{key}]")
                for k, v in val.items():
                    print(f"  {k} = {_mask_val(k, v)}")
            else:
                print(f"{key} = {_mask_val(key, val)}")
        print("─────────────────────────────")

    elif action == "get":
        val = get_dotted(args.key)
        if val is None:
            print(f"❌ Configuration key '{args.key}' not found.")
            sys.exit(1)
        print(val)

    elif action == "set":
        success, err = set_dotted(args.key, args.value)
        if not success:
            print(f"❌ Failed to set configuration: {err}")
            sys.exit(1)
        print(f"✓ Configuration updated: {args.key} = {args.value}")

    elif action == "reset":
        confirm = input("⚠️ Are you sure you want to reset ALL configurations to default values? (y/N): ").strip().lower()
        if confirm == "y":
            save_config(DEFAULTS)
            print("✓ Configuration reset to defaults successfully.")
        else:
            print("Reset cancelled.")
    else:
        print("Usage: memory-os config show|get|set|reset")
        sys.exit(1)
