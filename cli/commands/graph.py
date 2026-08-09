"""
Command: memory-os graph <repo>

Shows knowledge graph relationships for a repository.
"""

import sys


def execute(args):
    """Run the graph command."""
    if not getattr(args, "repo", None):
        print("Usage: memory-os graph <repository_name>")
        sys.exit(1)

    repo = args.repo
    from storage.graph import GraphStore
    g = GraphStore()
    rels = g.get_node_relationships("Repository", repo)

    print("========================================")
    print(f"GRAPH RELATIONSHIPS FOR REPOSITORY: {repo}")
    print("========================================")
    if not rels:
        print("No relationships found.")
    else:
        for r in sorted(rels):
            print(f"- {r}")
    print("========================================")
