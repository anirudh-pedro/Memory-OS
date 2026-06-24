import sys
from dotenv import load_dotenv
from storage.db import (
    init_db,
    get_repo_count,
    get_email_count,
    get_repository_details,
    search_local_knowledge,
    search_local_knowledge_ranked,
    get_repository_files,
    get_repository_readme,
    get_repository_summary_data,
    get_all_repositories
)
from storage.tech_detector import (
    detect_tech_for_repo,
    detect_all_tech,
    find_repos_by_tech
)
import re
from connectors.github import sync_github
from connectors.gmail import sync_gmail
from core.vector_store import (
    hybrid_search,
    run_reindexing,
    run_semantic_search,
    get_vector_index_stats
)

# Load environment variables (such as COMPOSIO_API_KEY)
load_dotenv()

# Force standard output to UTF-8 to handle Unicode characters smoothly on Windows
sys.stdout.reconfigure(encoding='utf-8')

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

def route_ask_question(question: str):
    q = question.strip().rstrip("?").lower()
    
    # Pattern 4: List all projects
    if q in ["list all projects", "list projects", "projects", "show all projects"]:
        return "projects", None
        
    # Pattern 1: What projects use X / Which repositories use X / Which projects contain X
    match_use = re.search(r"(?:what projects|which repositories|which projects|projects|repositories)\s+(?:use|contain|using|containing)\s+([a-zA-Z0-9.\-_#+]+)", q)
    if match_use:
        return "project-search", match_use.group(1).strip()
        
    # Fallback Pattern 1: projects using X
    match_use_alt = re.search(r"projects using\s+([a-zA-Z0-9.\-_#+]+)", q)
    if match_use_alt:
        return "project-search", match_use_alt.group(1).strip()
        
    # Pattern 2: What technologies are used in PROJECT
    match_tech = re.search(r"what technologies (?:are used in|in)\s+([a-zA-Z0-9.\-_#+]+)", q)
    if match_tech:
        return "project-tech", match_tech.group(1).strip()
        
    # Pattern 3: Tell me about PROJECT
    match_about = re.search(r"tell me about\s+([a-zA-Z0-9.\-_#+]+)", q)
    if match_about:
        return "repo-summary", match_about.group(1).strip()
        
    return None, None

def print_menu():
    print("==================================================")
    print("🧠 MEMORY-OS")
    print("==================================================")
    print("Commands:")
    print("  sync-github")
    print("  sync-gmail")
    print("  repo-info <repository_name>")
    print("  search <query> [--repos-only|--docs-only|--emails-only]")
    print("  repo-files <repository_name>")
    print("  repo-readme <repository_name>")
    print("  repo-summary <repository_name>")
    print("  export-documents")
    print("  reindex")
    print("  semantic-search <query> [--repos-only|--docs-only|--emails-only]")
    print("  debug-retrieval <query>")
    print("  vector-stats")
    print("  stats")
    print("  exit")
    print("==================================================")

def main():
    # Initialize SQLite database and tables
    init_db()
    
    print_menu()
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            
            user_input_lower = user_input.lower()
            
            if user_input_lower == "exit":
                break
                
            elif user_input_lower == "sync-github":
                sync_github()
                
            elif user_input_lower == "sync-gmail":
                sync_gmail()
                
            elif user_input_lower.startswith("repo-info"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: repo-info <repository_name>")
                else:
                    repo_name = parts[1].strip()
                    details = get_repository_details(repo_name)
                    if not details:
                        print(f"Repository '{repo_name}' not found in database. Run sync-github first.")
                    else:
                        print(f"Repository: {details['repo_name']}")
                        print(f"\nDescription:\n{details['description']}")
                        print(f"\nLanguage:\n{details['language']}")
                        print(f"\nStars:\n{details['stars']}")
                        print(f"\nForks:\n{details['forks']}")
                        
                        last_updated = details['updated_at']
                        if len(last_updated) >= 10:
                            last_updated = last_updated[:10]
                        print(f"\nLast Updated:\n{last_updated}")
                        
                        print("\nFiles Available:")
                        if details['files']:
                            for f in sorted(details['files']):
                                print(f"- {f}")
                        else:
                            print("- None")
                        
                        print("\nREADME Preview:")
                        readme = details['readme']
                        if readme:
                            preview = readme[:500]
                            print(preview)
                        else:
                            print("No README available.")
                
            elif user_input_lower.startswith("search"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: search <query> [--repos-only|--docs-only|--emails-only]")
                else:
                    full_query = parts[1].strip()
                    source_filter = None
                    if "--repos-only" in full_query:
                        source_filter = "repository"
                        full_query = full_query.replace("--repos-only", "").strip()
                    elif "--docs-only" in full_query:
                        source_filter = "document"
                        full_query = full_query.replace("--docs-only", "").strip()
                    elif "--emails-only" in full_query:
                        source_filter = "email"
                        full_query = full_query.replace("--emails-only", "").strip()
                        
                    results = hybrid_search(full_query, source_filter=source_filter)
                    
                    print("========================================")
                    print("SEARCH RESULTS")
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
                                content_to_preview = item.get("content") or ""
                                preview = get_preview_snippet(content_to_preview, full_query)
                                print(f"   Preview: {preview}")
                            elif t == "email":
                                print(f"{idx}. [Email] {item['subject']} (Score: {item['score']})")
                                print(f"   Sender: {item['sender']}")
                                snippet_to_preview = item.get("snippet") or ""
                                preview = get_preview_snippet(snippet_to_preview, full_query)
                                print(f"   Preview: {preview}")
                            print("-" * 40)
                    print("========================================")

            elif user_input_lower == "export-documents":
                # Calculate counts and chunks on the fly
                from storage.db import get_repo_count, get_email_count, get_repository_document_count, get_all_documents, get_all_emails
                from core.chunker import chunk_text
                
                repos_count = get_repo_count()
                emails_count = get_email_count()
                docs_count = get_repository_document_count()
                
                docs = get_all_documents()
                repo_docs_chunks = {}
                total_chunks = 0
                
                for doc in docs:
                    content = doc["content"] or ""
                    c_count = len(chunk_text(content))
                    total_chunks += c_count
                    repo_name = doc["repo_name"]
                    if repo_name not in repo_docs_chunks:
                        repo_docs_chunks[repo_name] = []
                    repo_docs_chunks[repo_name].append((doc["file_name"], c_count))
                    
                emails = get_all_emails()
                for email in emails:
                    email_text = f"Subject: {email['subject']}\nFrom: {email['sender']}\nDate: {email['received_at']}\nContent: {email['snippet']}"
                    total_chunks += len(chunk_text(email_text))
                    
                print("========================================")
                print("DOCUMENT EXPORT SUMMARY")
                print("========================================")
                print(f"Repositories: {repos_count}")
                print(f"Emails: {emails_count}")
                print(f"Documents: {docs_count}")
                print(f"\nChunks Generated: {total_chunks}")
                print()
                
                # Sort repositories case-insensitively
                for r_name in sorted(repo_docs_chunks.keys(), key=lambda s: s.lower()):
                    print("========================================")
                    print(f"\nRepository: {r_name}")
                    # Sort documents case-insensitively
                    sorted_docs = sorted(repo_docs_chunks[r_name], key=lambda x: x[0].lower())
                    for doc_name, chunks_count in sorted_docs:
                        print(f"\n{doc_name}")
                        print(f"\nChunks:\n{chunks_count}")
                    print()
                print("========================================")

            elif user_input_lower == "reindex":
                res = run_reindexing()
                print("========================================")
                print("REINDEX COMPLETE")
                print("========================================")
                print(f"\nDocuments: {res['documents']}")
                print(f"\nChunks: {res['chunks']}")
                print(f"\nCollection:\n{res['collection']}")
                print(f"\nDimension:\n{res['dimension']}")
                print(f"\nVectors Uploaded:\n{res['vectors_uploaded']}")
                print("\n========================================")

            elif user_input_lower.startswith("semantic-search"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: semantic-search <query> [--repos-only|--docs-only|--emails-only]")
                else:
                    full_query = parts[1].strip()
                    source_filter = None
                    if "--repos-only" in full_query:
                        source_filter = "repository"
                        full_query = full_query.replace("--repos-only", "").strip()
                    elif "--docs-only" in full_query:
                        source_filter = "document"
                        full_query = full_query.replace("--docs-only", "").strip()
                    elif "--emails-only" in full_query:
                        source_filter = "email"
                        full_query = full_query.replace("--emails-only", "").strip()
                        
                    results = run_semantic_search(full_query, limit=5, source_filter=source_filter)
                    
                    print("========================================")
                    print("SEMANTIC SEARCH RESULTS")
                    print("========================================")
                    print(f"\nQuery:\n\n{full_query}")
                    print("\nResults:")
                    if not results:
                        print("\nNo results found.")
                    else:
                        for idx, res in enumerate(results, start=1):
                            print(f"\n{idx}.\n")
                            print("Repository:")
                            print(res["repository_name"])
                            print("\nScore:")
                            print(f"{res['score']:.2f}")
                            print("\nChunk:\n")
                            print(res["chunk_text"])
                            if idx < len(results):
                                print("\n----------------------------------------")
                    print("\n========================================")

            elif user_input_lower.startswith("debug-retrieval"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: debug-retrieval <query>")
                else:
                    query = parts[1].strip()
                    results = run_semantic_search(query, limit=5, raw_scores=True)
                    
                    print("========================================")
                    print("RETRIEVAL DIAGNOSTICS")
                    print("========================================")
                    print(f"\nQuery:\n{query}")
                    print("\nTop Semantic Hits:")
                    if not results:
                        print("\nNo semantic hits found.")
                    else:
                        for idx, res in enumerate(results, start=1):
                            print(f"\n{idx}.\n")
                            print("Score:")
                            print(f"{res['score']:.2f}")
                            print("\nSource Type:")
                            print(res["source_type"])
                            print("\nRepository:")
                            print(res["repository_name"])
                            print("\nDocument:")
                            print(res["document_name"])
                            if idx < len(results):
                                print("\n----------------------------------------")
                    print("\n========================================")

            elif user_input_lower == "vector-stats":
                stats = get_vector_index_stats()
                print("========================================")
                print("VECTOR INDEX STATS")
                print("========================================")
                print(f"\nCollection:\n{stats['collection']}")
                print(f"\nDimension:\n{stats['dimension']}")
                print(f"\nVectors:\n{stats['vectors']}")
                print(f"\nEmbedding Model:\n{stats['embedding_model']}")
                print("\n========================================")

            elif user_input_lower == "projects":
                repos = get_all_repositories()
                print(f"Projects Found ({len(repos)})\n")
                if repos:
                    for i, r in enumerate(sorted(repos, key=lambda x: x["repo_name"].lower()), start=1):
                        print(f"{i}. {r['repo_name']}")
                else:
                    print("No projects stored yet.")

            elif user_input_lower == "tech-stack":
                techs = detect_all_tech()
                print("Technologies Found\n")
                if techs:
                    for t in techs:
                        print(f"- {t}")
                else:
                    print("No technologies discovered yet.")

            elif user_input_lower.startswith("project-tech"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: project-tech <repository_name>")
                else:
                    repo_name = parts[1].strip()
                    details = get_repository_details(repo_name)
                    if not details:
                        print(f"Repository '{repo_name}' not found in database. Run sync-github first.")
                    else:
                        techs = detect_tech_for_repo(repo_name)
                        print(f"Project: {details['repo_name']}\n")
                        print("Technologies:\n")
                        if techs:
                            for t in techs:
                                print(f"- {t}")
                        else:
                            print("- No technologies detected.")

            elif user_input_lower.startswith("project-search"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: project-search <technology>")
                else:
                    tech_name = parts[1].strip()
                    matching = find_repos_by_tech(tech_name)
                    print(f"Projects using {tech_name}:\n")
                    if matching:
                        for i, r in enumerate(matching, start=1):
                            print(f"{i}. {r}")
                    else:
                        print("No projects found using this technology.")

            elif user_input_lower.startswith("ask "):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: ask <question>")
                else:
                    question = parts[1].strip()
                    cmd_type, arg = route_ask_question(question)
                    
                    if cmd_type == "projects":
                        print(f"[Routing to projects]")
                        repos = get_all_repositories()
                        print(f"Projects Found ({len(repos)})\n")
                        if repos:
                            for i, r in enumerate(sorted(repos, key=lambda x: x["repo_name"].lower()), start=1):
                                print(f"{i}. {r['repo_name']}")
                        else:
                            print("No projects stored yet.")
                            
                    elif cmd_type == "project-search" and arg:
                        print(f"[Routing to project-search {arg}]")
                        matching = find_repos_by_tech(arg)
                        print(f"Projects using {arg}:\n")
                        if matching:
                            for i, r in enumerate(matching, start=1):
                                print(f"{i}. {r}")
                        else:
                            print("No projects found using this technology.")
                            
                    elif cmd_type == "project-tech" and arg:
                        print(f"[Routing to project-tech {arg}]")
                        details = get_repository_details(arg)
                        if not details:
                            print(f"Repository '{arg}' not found in database. Run sync-github first.")
                        else:
                            techs = detect_tech_for_repo(arg)
                            print(f"Project: {details['repo_name']}\n")
                            print("Technologies:\n")
                            if techs:
                                for t in techs:
                                    print(f"- {t}")
                            else:
                                print("- No technologies detected.")
                                
                    elif cmd_type == "repo-summary" and arg:
                        print(f"[Routing to repo-summary {arg}]")
                        summary = get_repository_summary_data(arg)
                        if not summary:
                            print(f"Repository '{arg}' not found in database. Run sync-github first.")
                        else:
                            print(f"Repository: {summary['repo_name']}")
                            print(f"\nLanguage:\n{summary['language']}")
                            print(f"\nStars:\n{summary['stars']}")
                            print(f"\nForks:\n{summary['forks']}")
                            print(f"\nDocuments:\n{summary['documents_count']}")
                            print("\nFiles:")
                            if summary['files']:
                                for f in sorted(summary['files']):
                                    print(f)
                            else:
                                print("None")
                            
                            last_updated = summary['updated_at']
                            if len(last_updated) >= 10:
                                last_updated = last_updated[:10]
                            print(f"\nLast Updated:\n{last_updated}")
                            print("\n========================================")
                            
                    else:
                        print("I'm sorry, I couldn't route that question to a query command. Please try a different wording.")

            elif user_input_lower.startswith("repo-files"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: repo-files <repository_name>")
                else:
                    repo_name = parts[1].strip()
                    details = get_repository_details(repo_name)
                    if not details:
                        print(f"Repository '{repo_name}' not found in database. Run sync-github first.")
                    else:
                        files = get_repository_files(repo_name)
                        print(f"Repository: {details['repo_name']}")
                        print("\nFiles Found:\n")
                        if files:
                            for f in sorted(files):
                                print(f"- {f}")
                        else:
                            print("- None")
                        print("\n========================================")

            elif user_input_lower.startswith("repo-readme"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: repo-readme <repository_name>")
                else:
                    repo_name = parts[1].strip()
                    details = get_repository_details(repo_name)
                    if not details:
                        print(f"Repository '{repo_name}' not found in database. Run sync-github first.")
                    else:
                        readme = get_repository_readme(repo_name)
                        print(f"Repository: {details['repo_name']}")
                        print("\nREADME:\n")
                        if readme:
                            print(readme)
                        else:
                            print("No README stored for this repository.")
                        print("\n========================================")

            elif user_input_lower.startswith("repo-summary"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: repo-summary <repository_name>")
                else:
                    repo_name = parts[1].strip()
                    summary = get_repository_summary_data(repo_name)
                    if not summary:
                        print(f"Repository '{repo_name}' not found in database. Run sync-github first.")
                    else:
                        print(f"Repository: {summary['repo_name']}")
                        print(f"\nLanguage:\n{summary['language']}")
                        print(f"\nStars:\n{summary['stars']}")
                        print(f"\nForks:\n{summary['forks']}")
                        print(f"\nDocuments:\n{summary['documents_count']}")
                        print("\nFiles:")
                        if summary['files']:
                            for f in sorted(summary['files']):
                                print(f)
                        else:
                            print("None")
                        
                        last_updated = summary['updated_at']
                        if len(last_updated) >= 10:
                            last_updated = last_updated[:10]
                        print(f"\nLast Updated:\n{last_updated}")
                        print("\n========================================")
                
            elif user_input_lower == "stats":
                repos = get_repo_count()
                emails = get_email_count()
                print("========================================")
                print("MEMORY-OS STATS")
                print("========================================")
                print(f"Repositories: {repos}")
                print(f"Emails: {emails}")
                print("========================================")
                
            else:
                print(f"Unknown command: '{user_input}'")
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
