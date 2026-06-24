import sys
from dotenv import load_dotenv
from storage.db import (
    init_db,
    get_repo_count,
    get_email_count,
    get_repository_details,
    search_local_knowledge,
    get_repository_files,
    get_repository_readme,
    get_repository_summary_data
)
from connectors.github import sync_github
from connectors.gmail import sync_gmail

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

def print_menu():
    print("==================================================")
    print("🧠 MEMORY-OS")
    print("==================================================")
    print("Commands:")
    print("  sync-github")
    print("  sync-gmail")
    print("  repo-info <repository_name>")
    print("  search <query>")
    print("  repo-files <repository_name>")
    print("  repo-readme <repository_name>")
    print("  repo-summary <repository_name>")
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
                    print("Usage: search <query>")
                else:
                    query = parts[1].strip()
                    results = search_local_knowledge(query)
                    
                    print("========================================")
                    print("SEARCH RESULTS")
                    print("========================================")
                    
                    # 1. Repositories
                    print("Repositories:")
                    if results["repositories"]:
                        for r in results["repositories"]:
                            print(f"\nRepository: {r['repo_name']}")
                            print(f"Language: {r['language']}")
                            print(f"\nDescription:\n{r['description']}")
                            print("-" * 40)
                    else:
                        print("\nNo matching repositories found.")
                        print("-" * 40)
                        
                    # 2. Documents
                    print("\nDocuments:")
                    if results["documents"]:
                        for d in results["documents"]:
                            print(f"\nRepository: {d['repo_name']}")
                            print(f"File: {d['file_name']}")
                            preview = get_preview_snippet(d['content'], query)
                            print(f"\nPreview:\n{preview}")
                            print("-" * 40)
                    else:
                        print("\nNo matching documents found.")
                        print("-" * 40)
                        
                    # 3. Emails
                    print("\nEmails:")
                    if results["emails"]:
                        for e in results["emails"]:
                            print(f"\nSubject:\n{e['subject']}")
                            print(f"\nSender:\n{e['sender']}")
                            preview = get_preview_snippet(e['snippet'], query)
                            print(f"\nPreview:\n{preview}")
                            print("-" * 40)
                    else:
                        print("\nNo matching emails found.")
                        print("-" * 40)
                        
                    print("========================================")

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
