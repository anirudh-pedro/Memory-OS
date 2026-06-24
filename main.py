import sys
from dotenv import load_dotenv
from storage.db import init_db, get_repo_count, get_email_count, get_repository_details
from connectors.github import sync_github
from connectors.gmail import sync_gmail

# Load environment variables (such as COMPOSIO_API_KEY)
load_dotenv()

# Force standard output to UTF-8 to handle Unicode characters smoothly on Windows
sys.stdout.reconfigure(encoding='utf-8')

def print_menu():
    print("==================================================")
    print("🧠 MEMORY-OS")
    print("==================================================")
    print("Commands:")
    print("  sync-github")
    print("  sync-gmail")
    print("  repo-info <repository_name>")
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
