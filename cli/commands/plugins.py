"""
Command: memory-os plugins

Displays installed and available connector plugins.
"""

from connectors.registry import discover_connectors


def execute(args):
    """Run the plugins command."""
    print("─────────────────────────────")
    print("  Memory-OS Connector Plugins")
    print("─────────────────────────────")

    # Discover active/installed connectors
    installed = discover_connectors()
    
    print("  Installed (Active):")
    for conn in installed:
        print(f"    ✓ {conn.name} ({conn.slug})")

    # Available but disabled / not-yet-integrated plugins
    disabled = [
        ("Slack", "slack"),
        ("Jira", "jira"),
        ("Google Drive", "google-drive")
    ]
    
    print("\n  Disabled (Available):")
    for name, slug in disabled:
        print(f"    - {name} ({slug})")

    print("─────────────────────────────")
    print("  To enable, run: memory-os config set composio.api_key <key>")
    print("  Then authenticate during: memory-os init")
    print("─────────────────────────────")
