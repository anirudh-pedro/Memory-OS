import logging
import sys
from dotenv import load_dotenv
from storage.db import (
    init_db,
    get_repo_count,
    get_email_count,
    get_repository_details,
    get_repository_files,
    get_repository_readme,
    get_all_repositories,
    clear_all,
    delete_data_before_date,
    get_repository_document_count,
    get_all_documents,
    get_all_emails,
    get_connection
)
from storage.tech_detector import (
    detect_tech_for_repo,
    detect_all_tech,
    find_repos_by_tech
)
from connectors.github import sync_github
from connectors.gmail import sync_gmail
from connectors.notion import sync_notion
from core.vector_store import (
    hybrid_search,
    run_reindexing,
    run_semantic_search,
    get_vector_index_stats,
    get_vector_chunks,
    count_vector_chunks,
    close_qdrant_client
)
from core.embedder import Embedder
from core.llm import run_hybrid_rag
from storage.graph import GraphStore

load_dotenv()

# Force standard output to UTF-8 to handle Unicode characters smoothly on Windows
sys.stdout.reconfigure(encoding='utf-8')

def print_menu():
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
    print("  repo-info <repo>           - Show metadata for repository")
    print("  repo-readme <repo>         - View README of repository")
    print("  repo-files <repo>          - List synced files for repository")
    print("  project-tech <repo>        - List detected technologies for repository")
    print("  projects                   - List all repositories")
    print("  tech-stack                 - List all detected technologies")
    print("  project-search <tech>      - Find projects using a technology")
    print("  graph <repo>               - Show graph relationships for repository")
    print("  graph-tech <tech>          - Show graph relationships for technology")
    print("  graph-person <person>      - Show graph relationships for contributor/user")
    print("  relations <entity>         - Search all graph relationships matching entity")
    print("  debug-index <repo>         - Show documents indexing summary")
    print("  debug-vector <repo>        - Print sample vector payloads")
    print("  debug-retrieval <query>    - Show retrieval scores & details")
    print("  vector-stats               - Show Qdrant index details")
    print("  delete --before YYYY-MM-DD - Delete records older than date")
    print("  reset                      - Reset all local storage")
    print("  exit                       - Exit Memory-OS")
    print("==================================================")

def get_preview_snippet(content: str, query: str, length: int = 120) -> str:
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

def setup_logging():
    """Configure standardized application-wide logging."""
    import os
    import logging
    os.makedirs("logs", exist_ok=True)
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    level = logging.DEBUG if debug_mode else logging.INFO
    
    # Configure logging format
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/memory_os.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr) if debug_mode else logging.NullHandler()
        ]
    )

def main():
    setup_logging()
    init_db()
    
    # Load SentenceTransformer model exactly once at startup
    print("Initializing embedding model...")
    embedder = Embedder()
    _ = embedder.model
    print("System ready.")

    print_menu()
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            
            user_input_lower = user_input.lower()
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            # Natural Language Routing
            VALID_COMMANDS = {
                "exit", "sync", "stats", "search", "semantic-search", "ask",
                "project-tech", "project-search", "graph", "graph-tech", 
                "graph-person", "relations", "debug-index", "debug-vector",
                "debug-retrieval", "vector-stats", "delete", "reset"
            }
            if cmd not in VALID_COMMANDS:
                is_natural_language = (
                    user_input.rstrip().endswith("?") or
                    cmd in {"what", "how", "which", "who", "where", "why", "when", "is", "are", "can", "do", "does", "tell", "show", "explain", "describe", "find", "list", "get", "explain", "help", "please"}
                )
                if is_natural_language:
                    arg = user_input
                    cmd = "ask"

            if cmd == "exit":
                print("Closing resources...")
                close_qdrant_client()
                # Close graph store driver if present
                GraphStore().close()
                print("Goodbye!")
                break
                
            elif cmd == "sync":
                import time
                start_time = time.perf_counter()
                if arg == "--rebuild":
                    print("Performing full rebuild reset...")
                    # 1. Reset
                    clear_all()
                    close_qdrant_client()
                    run_reindexing()  # Recreate collection
                    GraphStore().clear_graph()
                    
                    # 2. Sync all
                    sync_github()
                    sync_gmail()
                    sync_notion()
                    
                    # 3. Index & Build Graph
                    run_reindexing()
                    GraphStore().extract_and_sync_graph()
                    duration = time.perf_counter() - start_time
                    print(f"\nRebuild complete. Total Duration: {duration:.2f}s")
                    logging.getLogger("main").info(f"Full rebuild completed in {duration:.2f}s")
                else:
                    sync_github()
                    sync_gmail()
                    sync_notion()
                    # Reindex new content
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
                    print("Usage: semantic-search <query> [--repos-only|--docs-only|--emails-only]")
                else:
                    source_filter = None
                    query_text = arg
                    if "--repos-only" in arg:
                        source_filter = "repository"
                        query_text = arg.replace("--repos-only", "").strip()
                    elif "--docs-only" in arg:
                        source_filter = "document"
                        query_text = arg.replace("--docs-only", "").strip()
                    elif "--emails-only" in arg:
                        source_filter = "email"
                        query_text = arg.replace("--emails-only", "").strip()
                        
                    results = run_semantic_search(query_text, limit=5, source_filter=source_filter)
                    print("========================================")
                    print("SEMANTIC SEARCH RESULTS")
                    print("========================================")
                    print(f"Query: {query_text}")
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
                    rag_res = run_hybrid_rag(arg)
                    print("========================================")
                    print("ANSWER")
                    print("========================================")
                    print(rag_res["answer"])
                    print("\n========================================")
                    print("SOURCES")
                    print("========================================")
                    if rag_res["sources"]:
                        for s in rag_res["sources"]:
                            print(f"- {s}")
                    else:
                        print("None")
                    print("\n========================================")
                    print("REPOSITORIES USED")
                    print("========================================")
                    if rag_res["repositories"]:
                        for r in rag_res["repositories"]:
                            print(f"- {r}")
                    else:
                        print("None")
                    print("\n========================================")
                    print(f"Confidence: {rag_res['confidence']:.2f}")
                    print("========================================")

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

            elif cmd == "repo-readme":
                if not arg:
                    print("Usage: repo-readme <repository_name>")
                else:
                    readme = get_repository_readme(arg)
                    if readme:
                        print(readme)
                    else:
                        print(f"No README found for {arg}.")

            elif cmd == "repo-files":
                if not arg:
                    print("Usage: repo-files <repository_name>")
                else:
                    files = get_repository_files(arg)
                    if files:
                        print(f"Files for {arg}:")
                        for f in sorted(files):
                            print(f"- {f}")
                    else:
                        print(f"No files found for {arg}.")

            elif cmd == "project-tech":
                if not arg:
                    print("Usage: project-tech <repository_name>")
                else:
                    techs = detect_tech_for_repo(arg)
                    print(f"Technologies used in {arg}:")
                    if techs:
                        for t in techs:
                            print(f"- {t}")
                    else:
                        print("None detected.")

            elif cmd == "projects":
                repos = get_all_repositories()
                print(f"Projects Found ({len(repos)}):")
                for idx, r in enumerate(sorted(repos, key=lambda x: x["repo_name"].lower()), start=1):
                    print(f"{idx}. {r['repo_name']}")

            elif cmd == "tech-stack":
                techs = detect_all_tech()
                print("All detected technologies:")
                for t in techs:
                    print(f"- {t}")

            elif cmd == "project-search":
                if not arg:
                    print("Usage: project-search <technology>")
                else:
                    matching = find_repos_by_tech(arg)
                    print(f"Projects using {arg}:")
                    if matching:
                        for idx, r in enumerate(matching, start=1):
                            print(f"{idx}. {r}")
                    else:
                        print("None found.")

            elif cmd == "debug-index":
                if not arg:
                    print("Usage: debug-index <repository_name>")
                else:
                    # Case-insensitive resolution of repository name
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT DISTINCT repo_name FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)",
                        (arg,)
                    )
                    row = cursor.fetchone()
                    actual_repo_name = row[0] if row else arg

                    # Show documents, chunk counts, character lengths, and vectors uploaded for repo
                    cursor.execute(
                        "SELECT file_name, LENGTH(content) FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)",
                        (actual_repo_name,)
                    )
                    docs = cursor.fetchall()
                    
                    total_chunks = 0
                    if docs:
                        from core.chunker import chunk_text
                        for file_name, length in docs:
                            cursor.execute(
                                "SELECT content FROM repository_documents WHERE LOWER(repo_name) = LOWER(?) AND file_name = ?",
                                (actual_repo_name, file_name)
                            )
                            content = cursor.fetchone()[0] or ""
                            chunks = len(chunk_text(content))
                            total_chunks += chunks

                    # Qdrant count check
                    qdrant_vectors = count_vector_chunks(actual_repo_name)
                    
                    print("========================================")
                    print(f"INDEX DIAGNOSTICS")
                    print("========================================")
                    print(f"Repository:      {actual_repo_name}")
                    print(f"Documents:       {len(docs)}")
                    print(f"Chunks:          {total_chunks}")
                    print(f"Total vectors:   {qdrant_vectors}")
                    print(f"Embedding model: all-MiniLM-L6-v2")
                    print(f"Collection name: memory_os")
                    print("========================================")
                    conn.close()

            elif cmd == "debug-vector":
                if not arg:
                    print("Usage: debug-vector <repository_name>")
                else:
                    # Case-insensitive resolution of repository name
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT DISTINCT repo_name FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)",
                        (arg,)
                    )
                    row = cursor.fetchone()
                    actual_repo_name = row[0] if row else arg
                    conn.close()

                    # Print first 5 vector payloads
                    vectors = get_vector_chunks(actual_repo_name, limit=5)
                    print("========================================")
                    print(f"VECTOR DIAGNOSTICS (Sample 5): {actual_repo_name}")
                    print("========================================")
                    if not vectors:
                        print("No vectors found in Qdrant for this repository.")
                    else:
                        for idx, record in enumerate(vectors, start=1):
                            payload = record.payload
                            chunk_text = payload.get("chunk_text", "")
                            chunk_preview = chunk_text[:100] + "..." if len(chunk_text) > 100 else chunk_text
                            print(f"Vector {idx}:")
                            print(f"  Repository:              {payload.get('repository_name')}")
                            print(f"  Document:                {payload.get('document_name')}")
                            print(f"  Chunk Index:             {payload.get('chunk_index')}")
                            print(f"  Chunk Length:            {len(chunk_text)}")
                            print(f"  Vector ID:               {record.id}")
                            print(f"  Similarity (if available): N/A")
                            print(f"  Chunk Preview:           {chunk_preview.strip().replace('\n', ' ')}")
                            print("-" * 30)
                    print("========================================")

            elif cmd == "debug-retrieval":
                if not arg:
                    print("Usage: debug-retrieval <query>")
                else:
                    # Return search results with retrieval score, source, repository, document, ranking reason
                    results = run_semantic_search(arg, limit=5)
                    print("========================================")
                    print(f"RETRIEVAL DIAGNOSTICS: '{arg}'")
                    print("========================================")
                    if not results:
                        print("No matches found.")
                    else:
                        for idx, res in enumerate(results, start=1):
                            print(f"Rank {idx}:")
                            print(f"  Similarity Score: {res['score']:.4f}")
                            print(f"  Source Type: {res['source_type']}")
                            print(f"  Repository: {res['repository_name']}")
                            print(f"  Document/Subject: {res['document_name']}")
                            
                            # Determine ranking reason
                            reason = "Semantic match using cosine similarity."
                            if "readme" in res['document_name'].lower():
                                reason += " (README document priority boost applied)"
                            if res['source_type'] == "document":
                                reason += " (Document source type boost applied)"
                            elif res['source_type'] == "email":
                                reason += " (Email score weights applied)"
                            print(f"  Ranking Reason: {reason}")
                            print("-" * 30)
                    print("========================================")

            elif cmd == "vector-stats":
                stats = get_vector_index_stats()
                print("========================================")
                print("VECTOR INDEX STATS")
                print("========================================")
                print(f"Collection: {stats['collection']}")
                print(f"Dimension: {stats['dimension']}")
                print(f"Vectors Count: {stats['vectors']}")
                print(f"Embedding Model: {stats['embedding_model']}")
                print(f"Collection Exists: {stats['exists']}")
                print("========================================")

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

            elif cmd == "graph-tech":
                if not arg:
                    print("Usage: graph-tech <technology_name>")
                else:
                    g = GraphStore()
                    rels = g.get_node_relationships("Technology", arg)
                    print("========================================")
                    print(f"GRAPH RELATIONSHIPS FOR TECHNOLOGY: {arg}")
                    print("========================================")
                    if not rels:
                        print("No relationships found.")
                    else:
                        for r in sorted(rels):
                            print(f"- {r}")
                    print("========================================")

            elif cmd == "graph-person":
                if not arg:
                    print("Usage: graph-person <person_name>")
                else:
                    g = GraphStore()
                    rels = g.get_node_relationships("User", arg)
                    print("========================================")
                    print(f"GRAPH RELATIONSHIPS FOR PERSON: {arg}")
                    print("========================================")
                    if not rels:
                        print("No relationships found.")
                    else:
                        for r in sorted(rels):
                            print(f"- {r}")
                    print("========================================")

            elif cmd == "relations":
                if not arg:
                    print("Usage: relations <entity_name>")
                else:
                    g = GraphStore()
                    rels = g.lookup_relationships(arg)
                    print("========================================")
                    print(f"GRAPH RELATIONSHIPS FOR ENTITY: {arg}")
                    print("========================================")
                    if not rels:
                        print("No relationships found.")
                    else:
                        for r in sorted(rels):
                            print(f"- {r}")
                    print("========================================")

            elif cmd == "delete":
                if not arg or not arg.startswith("--before"):
                    print("Usage: delete --before YYYY-MM-DD")
                else:
                    date_str = arg.replace("--before", "").strip()
                    res = delete_data_before_date(date_str)
                    print("========================================")
                    print(f"DELETE OPERATIONS BEFORE {date_str}")
                    print("========================================")
                    print(f"Emails Deleted: {res['emails']}")
                    print(f"Documents Deleted: {res['documents']}")
                    print(f"Document Chunks Deleted: {res['chunks']}")
                    
                    # Reindex remaining items
                    print("Rebuilding Qdrant index...")
                    run_reindexing()
                    print("Rebuilding Graph Store relationships...")
                    GraphStore().extract_and_sync_graph()
                    print("Deletion & Reindex Complete.")
                    print("========================================")

            elif cmd == "reset":
                confirm = input("Are you sure you want to reset all data? (y/N): ").strip().lower()
                if confirm == "y":
                    clear_all()
                    close_qdrant_client()
                    run_reindexing()  # Recreate empty collection
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
        except Exception as e:
            print(f"Error during command execution: {e}")

if __name__ == "__main__":
    main()
