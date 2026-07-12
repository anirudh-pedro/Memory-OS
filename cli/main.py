"""
Memory-OS CLI entry point.

Handles argument parsing, config loading, command routing,
and the interactive REPL.
"""

import logging
import os
import sys

from cli.parser import build_parser


def setup_logging():
    """Configure standardized rotating logging."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path
    
    try:
        from infrastructure.workspace import get_logs_path
        logs_dir = get_logs_path()
    except Exception:
        logs_dir = Path("logs")
        
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "memory_os.log"
    
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    level = logging.DEBUG if debug_mode else logging.INFO

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    file_handler.setLevel(level)

    stream_handler = logging.StreamHandler(sys.stderr) if debug_mode else logging.NullHandler()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
        
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


def get_preview_snippet(content: str, query: str, length: int = 120) -> str:
    """Extract a relevant preview snippet from content around the query match."""
    if not content:
        return ""
    idx = content.lower().find(query.lower())
    if idx != -1:
        start = max(0, idx - 40)
        if start > 0:
            space_idx = content.find(" ", start, idx)
            if space_idx != -1:
                start = space_idx + 1
        end = min(len(content), idx + len(query) + 80)
        if end < len(content):
            space_idx = content.rfind(" ", idx + len(query), end)
            if space_idx != -1 and space_idx > idx + len(query):
                end = space_idx

        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return prefix + content[start:end].replace("\n", " ").replace("\r", " ").strip() + suffix
    else:
        snippet = content[:length].replace("\n", " ").replace("\r", " ").strip()
        if len(content) > length:
            snippet += "..."
        return snippet


def print_menu():
    """Print the interactive REPL menu."""
    print("==================================================")
    print("🧠 MEMORY-OS CLI")
    print("==================================================")
    print("Commands:")
    print("  sync                       - Incremental sync from all sources")
    print("  sync --rebuild             - Full reset and sync from all sources")
    print("  stats                      - Show database record counts")
    print("  search <query>             - Hybrid search across knowledge base")
    print("  semantic-search <query>    - Semantic search in vector index")
    print("  ask <question>             - Query RAG pipeline for grounded answer")
    print("  projects                   - List all repositories")
    print("  repo-info <repo>           - Show details for repository")
    print("  graph <repo>               - Show graph relationships for repository")
    print("  reset                      - Reset all local storage")
    print("  exit                       - Exit Memory-OS")
    print("==================================================")


def run_interactive():
    """Run the interactive REPL loop (preserves all existing behavior)."""
    from storage.db import (
        init_db,
        get_repo_count,
        get_email_count,
        get_repository_details,
        get_repository_document_count,
        get_all_repositories,
        clear_all,
    )
    from core.vector_store import (
        hybrid_search,
        run_reindexing,
        run_semantic_search,
        close_qdrant_client,
    )
    from core.embedder import Embedder
    from storage.graph import GraphStore
    from connectors.github import sync_github
    from connectors.gmail import sync_gmail
    from connectors.notion import sync_notion

    import sqlite3
    try:
        init_db()
    except sqlite3.OperationalError as e:
        import logging
        logging.getLogger("repl").exception("Database operational error in REPL startup")
        print("----------------------------------")
        print("Workspace not initialized.")
        print("")
        print("Run:")
        print("memory-os init")
        print("----------------------------------")
        return
    except Exception as e:
        import logging
        logging.getLogger("repl").exception("Unexpected error in REPL startup database init")
        print(f"❌ Failed to initialize database: {e}")
        return

    # Load SentenceTransformer model exactly once at startup
    try:
        print("Initializing embedding model...")
        embedder = Embedder()
        _ = embedder.model
        print("System ready.")
    except Exception as e:
        import logging
        logging.getLogger("repl").exception("Failed to initialize embedding model in REPL")
        print(f"⚠️ Warning: Failed to initialize embedding model: {e}")
        print("Model will download automatically on first query.")

    print_menu()

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue

            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            # Natural Language Routing
            VALID_COMMANDS = {
                "exit", "sync", "stats", "search", "semantic-search", "ask",
                "projects", "repo-info", "graph", "reset"
            }
            if cmd not in VALID_COMMANDS:
                is_natural_language = (
                    user_input.rstrip().endswith("?") or
                    cmd in {"what", "how", "which", "who", "where", "why", "when",
                            "is", "are", "can", "do", "does", "tell", "show",
                            "explain", "describe", "find", "list", "get", "help", "please"}
                )
                if is_natural_language:
                    arg = user_input
                    cmd = "ask"

            if cmd == "exit":
                print("Closing resources...")
                close_qdrant_client()
                GraphStore().close()
                print("Goodbye!")
                break

            elif cmd == "sync":
                import time
                start_time = time.perf_counter()
                if arg == "--rebuild":
                    print("Performing full rebuild reset...")
                    clear_all()
                    close_qdrant_client()
                    run_reindexing()
                    GraphStore().clear_graph()

                    sync_github()
                    sync_gmail()
                    sync_notion()

                    run_reindexing()
                    GraphStore().extract_and_sync_graph()
                    duration = time.perf_counter() - start_time
                    print(f"\nRebuild complete. Total Duration: {duration:.2f}s")
                    logging.getLogger("main").info(f"Full rebuild completed in {duration:.2f}s")
                else:
                    sync_github()
                    sync_gmail()
                    sync_notion()
                    run_reindexing()
                    GraphStore().extract_and_sync_graph()
                    duration = time.perf_counter() - start_time
                    print(f"\nSync complete. Total Duration: {duration:.2f}s")
                    logging.getLogger("main").info(f"Sync completed in {duration:.2f}s")

            elif cmd == "stats":
                repos = get_repo_count()
                emails = get_email_count()
                docs = get_repository_document_count()
                print("========================================")
                print("MEMORY-OS STATS")
                print("========================================")
                print(f"Repositories: {repos}")
                print(f"Documents: {docs}")
                print(f"Emails: {emails}")
                print("========================================")

            elif cmd == "search":
                if not arg:
                    print("Usage: search <query>")
                else:
                    results = hybrid_search(arg)
                    print("========================================")
                    print("HYBRID SEARCH RESULTS")
                    print("========================================")
                    if not results:
                        print("No matching results found.")
                    else:
                        for idx, item in enumerate(results, start=1):
                            t = item["type"]
                            if t == "repository":
                                print(f"{idx}. [Repository] {item['repo_name']} (Score: {item['score']})")
                                print(f"   Language: {item['language']}")
                                desc = item['description'] or "No description."
                                desc_cleaned = desc.replace("\n", " ").replace("\r", " ").strip()
                                print(f"   Description: {desc_cleaned}")
                            elif t == "document":
                                print(f"{idx}. [Document] {item['repo_name']} - {item['file_name']} (Score: {item['score']})")
                                preview = get_preview_snippet(item.get("content") or "", arg)
                                print(f"   Preview: {preview}")
                            elif t == "email":
                                print(f"{idx}. [Email] {item['subject']} (Score: {item['score']})")
                                print(f"   Sender: {item['sender']}")
                                preview = get_preview_snippet(item.get("snippet") or "", arg)
                                print(f"   Preview: {preview}")
                            print("-" * 40)
                    print("========================================")

            elif cmd == "semantic-search":
                if not arg:
                    print("Usage: semantic-search <query>")
                else:
                    results = run_semantic_search(arg, limit=5, source_filter=None)
                    print("========================================")
                    print("SEMANTIC SEARCH RESULTS")
                    print("========================================")
                    print(f"Query: {arg}")
                    if not results:
                        print("No results found.")
                    else:
                        for idx, res in enumerate(results, start=1):
                            print(f"{idx}. [Source: {res['source_type']}] (Score: {res['score']:.4f})")
                            print(f"   Repository: {res['repository_name']}")
                            print(f"   Document: {res['document_name']}")
                            print(f"   Chunk Text: {res['chunk_text']}")
                            print("-" * 40)
                    print("========================================")

            elif cmd == "ask":
                if not arg:
                    print("Usage: ask <question>")
                else:
                    from cli.commands.ask import run_and_print_ask
                    try:
                        run_and_print_ask(arg)
                    except Exception as e:
                        print(f"❌ Error executing query: {e}")

            elif cmd == "repo-info":
                if not arg:
                    print("Usage: repo-info <repository_name>")
                else:
                    details = get_repository_details(arg)
                    if not details:
                        print(f"Repository '{arg}' not found.")
                    else:
                        print(f"Repository: {details['repo_name']}")
                        print(f"Description: {details['description']}")
                        print(f"Language: {details['language']}")
                        print(f"Stars: {details['stars']}")
                        print(f"Forks: {details['forks']}")
                        print(f"Last Updated: {details['updated_at'][:10] if details['updated_at'] else 'N/A'}")
                        print("Files synced:")
                        for f in sorted(details['files']):
                            print(f"- {f}")
                        if details['readme']:
                            print("\nREADME Preview:")
                            print(details['readme'][:400] + "...")

            elif cmd == "projects":
                repos = get_all_repositories()
                print(f"Projects Found ({len(repos)}):")
                for idx, r in enumerate(sorted(repos, key=lambda x: x["repo_name"].lower()), start=1):
                    print(f"{idx}. {r['repo_name']}")

            elif cmd == "graph":
                if not arg:
                    print("Usage: graph <repository_name>")
                else:
                    g = GraphStore()
                    rels = g.get_node_relationships("Repository", arg)
                    print("========================================")
                    print(f"GRAPH RELATIONSHIPS FOR REPOSITORY: {arg}")
                    print("========================================")
                    if not rels:
                        print("No relationships found.")
                    else:
                        for r in sorted(rels):
                            print(f"- {r}")
                    print("========================================")

            elif cmd == "reset":
                confirm = input("Are you sure you want to reset all data? (y/N): ").strip().lower()
                if confirm == "y":
                    clear_all()
                    close_qdrant_client()
                    run_reindexing()
                    GraphStore().clear_graph()
                    print("All data reset successfully.")
                else:
                    print("Reset cancelled.")

            else:
                print(f"Unknown command: '{cmd}'. Type exit to quit or sync to pull latest data.")

        except KeyboardInterrupt:
            print("\nClosing resources...")
            close_qdrant_client()
            GraphStore().close()
            print("Goodbye!")
            break
        except sqlite3.OperationalError as e:
            import logging
            logging.getLogger("repl").exception("Database operational error in REPL loop")
            print("----------------------------------")
            print("Workspace has not been initialized.")
            print("")
            print("Run:")
            print("memory-os init")
            print("----------------------------------")
        except Exception as e:
            import logging
            logging.getLogger("repl").exception("Unexpected error during command execution in REPL")
            print(f"Error during command execution: {e}")


def route_command(args):
    """Route a parsed subcommand to its handler module."""
    command = args.command

    if command is None:
        # No subcommand given — launch full-screen Textual TUI
        from cli.tui.app import MemoryOSTUIApp
        app = MemoryOSTUIApp()
        app.run()
        return

    # Import and execute the appropriate command module
    if command == "doctor":
        from cli.commands.doctor import execute
        execute(args)
    elif command == "version":
        from cli.commands.version import execute
        execute(args)
    elif command == "status":
        from cli.commands.status import execute
        execute(args)
    elif command == "init":
        from cli.commands.init import execute
        execute(args)
    elif command == "start":
        from cli.commands.start import execute
        execute(args)
    elif command == "stop":
        from cli.commands.stop import execute
        execute(args)
    elif command == "restart":
        from cli.commands.restart import execute
        execute(args)
    elif command == "plugins":
        from cli.commands.plugins import execute
        execute(args)
    elif command == "monitor":
        from cli.commands.monitor import execute
        execute(args)
    elif command == "export":
        from cli.commands.export import execute
        execute(args)
    elif command == "import":
        from cli.commands.import_cmd import execute
        execute(args)
    elif command == "config":
        from cli.commands.config_cmd import execute
        execute(args)
    elif command == "workspace":
        from cli.commands.workspace import execute
        execute(args)
    elif command == "benchmark":
        from cli.commands.benchmark import execute
        execute(args)
    elif command == "logs":
        from cli.commands.logs import execute
        execute(args)
    elif command == "sync":
        from cli.commands.sync import execute
        execute(args)
    elif command == "ask":
        from cli.commands.ask import execute
        execute(args)
    else:
        from cli.parser import build_parser
        build_parser().print_help()
        sys.exit(1)



def cli_entrypoint():
    """Main CLI entry point. Called by `memory-os` console script and `python main.py`."""
    # Force UTF-8 stdout on Windows
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    setup_logging()

    # Load configuration (TOML → .env → defaults)
    try:
        from infrastructure.config import load_config
        load_config()
    except Exception:
        # Config loading is best-effort at this stage; .env fallback
        # still works via load_dotenv in config.py
        from dotenv import load_dotenv
        load_dotenv()

    parser = build_parser()
    args = parser.parse_args()
    
    import logging
    import sqlite3
    logger = logging.getLogger("cli.main")
    
    try:
        route_command(args)
    except sqlite3.OperationalError as e:
        logger.exception("Database operational error occurred")
        print("----------------------------------")
        print("Workspace has not been initialized.")
        print("")
        print("Run:")
        print("memory-os init")
        print("----------------------------------")
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error in command execution")
        print(f"❌ An unexpected error occurred: {e}")
        print("Please check logs/memory_os.log for full details.")
        sys.exit(1)


if __name__ == "__main__":
    cli_entrypoint()

