from composio import Composio
from models.memory import Repository
from storage.db import insert_repository

def sync_github():
    try:
        c = Composio()
        s = c.create(user_id="user_123")
        
        # Verify connection
        toolkits_info = s.toolkits()
        github_tk = next((t for t in toolkits_info.items if t.slug == "github"), None)
        if not github_tk or not (github_tk.connection and github_tk.connection.is_active):
            print("GitHub connection not active.")
            return

        # Fetch repositories
        resp = s.execute(tool_slug="github_list_repositories_for_the_authenticated_user", arguments={})
        if resp.error or not resp.data:
            print("No repositories found.")
            return

        repos = resp.data.get("repositories", [])
        if not repos:
            print("No repositories found.")
            return

        print(f"Found {len(repos)} repositories")
        
        for repo in repos:
            repo_name = repo.get("name")
            description = repo.get("description") or ""
            language = repo.get("language") or "N/A"
            url = repo.get("html_url")
            last_updated = repo.get("updated_at") or ""

            # Save to SQLite
            db_repo = Repository(
                repo_name=repo_name,
                description=description,
                language=language,
                url=url,
                last_updated=last_updated
            )
            insert_repository(db_repo)

            # Print to terminal
            print("--------------------------------------------------")
            print(f"Repository: {repo_name}")
            print(f"Language: {language}")
            print(f"URL: {url}")
            print("--------------------------------------------------")
            
    except Exception as e:
        print(f"Error during GitHub sync: {e}")
