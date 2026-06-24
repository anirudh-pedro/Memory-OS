import sys
from dotenv import load_dotenv
from storage.db import init_db, get_repo_count, get_email_count
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
