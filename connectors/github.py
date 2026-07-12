import base64
from datetime import datetime
from composio import Composio
from models.memory import Repository, RepositoryDocument
from storage.db import (
    insert_repository,
    insert_repository_document,
    get_repo_count,
    get_repository_document_count,
    get_repository_details
)

def decode_github_content(content_str: str, encoding: str = "base64") -> str:
    if not content_str:
        return ""
    cleaned = content_str.replace("\n", "").replace("\r", "").strip()
    try:
        decoded_bytes = base64.b64decode(cleaned)
        return decoded_bytes.decode("utf-8", errors="ignore")
    except Exception:
        return content_str

def extract_metadata(data: dict):
    repo_name = data.get("name") or ""
    description = data.get("description") or ""
    language = data.get("language") or "N/A"
    visibility = data.get("visibility") or "public"
    
    stars = data.get("stargazers_count")
    if stars is None:
        stars = data.get("stars") or 0
        
    forks = data.get("forks_count")
    if forks is None:
        forks = data.get("forks") or 0
        
    open_issues = data.get("open_issues_count")
    if open_issues is None:
        open_issues = data.get("open_issues") or 0
        
    default_branch = data.get("default_branch") or "main"
    updated_at = data.get("updated_at") or ""
    url = data.get("html_url") or data.get("url") or ""
    
    return repo_name, description, language, visibility, stars, forks, open_issues, default_branch, updated_at, url

import os
import sys

def sync_github():
    try:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
            
        c = Composio()
        user_id = os.getenv("COMPOSIO_USER_ID", "user_123")
        s = c.create(user_id=user_id)
        
        # Verify connection
        toolkits_info = s.toolkits()
        github_tk = next((t for t in toolkits_info.items if t.slug == "github"), None)
        if not github_tk or not (github_tk.connection and github_tk.connection.is_active):
            print("GitHub connection not active.")
            return

        print("Syncing GitHub...\n")
        
        # Fetch repositories with pagination
        repos = []
        page = 1
        while True:
            resp = s.execute(
                tool_slug="github_list_repositories_for_the_authenticated_user",
                arguments={"per_page": 100, "page": page}
            )
            if resp.error or not resp.data:
                break
                
            resp_data = resp.data
            if isinstance(resp_data, dict) and "response_data" in resp_data:
                resp_data = resp_data["response_data"]
                
            page_repos = []
            if isinstance(resp_data, list):
                page_repos = resp_data
            elif isinstance(resp_data, dict):
                page_repos = resp_data.get("repositories") or resp_data.get("items") or []
                
            if not isinstance(page_repos, list) or not page_repos:
                break
                
            repos.extend(page_repos)
            if len(page_repos) < 100:
                break
            page += 1

        if not repos:
            print("No repositories found.")
            return

        print(f"Found {len(repos)} repositories\n")
        
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            repo_name = repo.get("name")
            if not repo_name:
                continue

            # Incremental sync check
            existing = get_repository_details(repo_name)
            if existing:
                existing_updated_at = existing.get("updated_at") or ""
                repo_updated_at = repo.get("updated_at") or ""
                if existing_updated_at and repo_updated_at and existing_updated_at[:19] == repo_updated_at[:19]:
                    if existing.get("files"):
                        print(f"Repository {repo_name} is up-to-date. Skipping sync.")
                        continue
                
            full_name = repo.get("full_name", "")
            owner = None
            if repo.get("owner") and isinstance(repo.get("owner"), dict):
                owner = repo.get("owner", {}).get("login")
            if not owner and "/" in full_name:
                owner = full_name.split("/")[0]
            if not owner:
                continue

            # Fetch detailed metadata
            try:
                resp_meta = s.execute(
                    tool_slug="github_get_a_repository",
                    arguments={"owner": owner, "repo": repo_name}
                )
                if resp_meta and not resp_meta.error and resp_meta.data:
                    meta_data = resp_meta.data
                    if "response_data" in meta_data and isinstance(meta_data["response_data"], dict):
                        meta_data = meta_data["response_data"]
                else:
                    meta_data = repo
            except Exception:
                meta_data = repo

            # Extract & Save Repository Metadata
            repo_name, description, language, visibility, stars, forks, open_issues, default_branch, updated_at, url = extract_metadata(meta_data)
            db_repo = Repository(
                repo_name=repo_name,
                description=description,
                language=language,
                visibility=visibility,
                stars=stars,
                forks=forks,
                open_issues=open_issues,
                default_branch=default_branch,
                updated_at=updated_at,
                url=url
            )
            insert_repository(db_repo)

            stored_files = {
                "README.md": False,
                "package.json": False,
                "requirements.txt": False
            }
            
            # Fetch README
            readme_stored = False
            synced_at_str = datetime.now().isoformat()
            try:
                resp_readme = s.execute(
                    tool_slug="github_get_a_repository_readme",
                    arguments={"owner": owner, "repo": repo_name}
                )
                if resp_readme and not resp_readme.error and resp_readme.data:
                    readme_data = resp_readme.data
                    if "response_data" in readme_data and isinstance(readme_data["response_data"], dict):
                        readme_data = readme_data["response_data"]
                    if "content" in readme_data and isinstance(readme_data["content"], dict):
                        readme_data = readme_data["content"]
                    
                    raw_content = readme_data.get("content") or ""
                    encoding = readme_data.get("encoding") or "base64"
                    decoded_readme = decode_github_content(raw_content, encoding)
                    if decoded_readme.strip():
                        doc = RepositoryDocument(
                            repo_name=repo_name,
                            file_name="README.md",
                            content=decoded_readme,
                            source="github_get_a_repository_readme",
                            synced_at=synced_at_str
                        )
                        insert_repository_document(doc)
                        stored_files["README.md"] = True
                        readme_stored = True
            except Exception:
                pass

            # Fetch specific configuration files
            files_to_check = ["README.md", "package.json", "requirements.txt", "pyproject.toml", "docker-compose.yml", "Dockerfile"]
            for file_path in files_to_check:
                if file_path == "README.md" and readme_stored:
                    continue
                
                try:
                    resp_file = s.execute(
                        tool_slug="github_get_repository_content",
                        arguments={"owner": owner, "repo": repo_name, "path": file_path}
                    )
                    if resp_file and not resp_file.error and resp_file.data:
                        file_data = resp_file.data
                        if "response_data" in file_data and isinstance(file_data["response_data"], dict):
                            file_data = file_data["response_data"]
                        if "content" in file_data and isinstance(file_data["content"], dict):
                            file_data = file_data["content"]
                        
                        raw_content = file_data.get("content")
                        if raw_content:
                            encoding = file_data.get("encoding") or "base64"
                            decoded_content = decode_github_content(raw_content, encoding)
                            if decoded_content.strip():
                                doc = RepositoryDocument(
                                    repo_name=repo_name,
                                    file_name=file_path,
                                    content=decoded_content,
                                    source="github_get_repository_content",
                                    synced_at=synced_at_str
                                )
                                insert_repository_document(doc)
                                if file_path in stored_files:
                                    stored_files[file_path] = True
                except Exception:
                    pass

            # Print repository sync details
            print("--------------------------------------------------")
            print(f"Repository: {repo_name}")
            print(f"Language: {language}")
            print(f"Stars: {stars}")
            print(f"Forks: {forks}")
            print(f"README: {'✓' if stored_files['README.md'] else '✗'}")
            print(f"package.json: {'✓' if stored_files['package.json'] else '✗'}")
            print(f"requirements.txt: {'✓' if stored_files['requirements.txt'] else '✗'}")
            print("--------------------------------------------------")
            print()

        # Print final summary stats
        total_repos = get_repo_count()
        total_docs = get_repository_document_count()
        print("GitHub Sync Complete")
        print(f"Repositories Stored: {total_repos}")
        print(f"Documents Stored: {total_docs}")

    except Exception as e:
        print(f"Error during GitHub sync: {e}")


from connectors.base import BaseConnector
from connectors.registry import register

@register
class GitHubConnector(BaseConnector):
    name = "GitHub"
    slug = "github"

    def authenticate(self) -> bool:
        try:
            c = Composio()
            user_id = os.getenv("COMPOSIO_USER_ID", "user_123")
            s = c.create(user_id=user_id)
            toolkits_info = s.toolkits()
            tk = next((t for t in toolkits_info.items if t.slug == "github"), None)
            return bool(tk and tk.connection and tk.connection.is_active)
        except Exception:
            return False

    def sync(self) -> dict:
        sync_github()
        return {"status": "success"}

    def health(self) -> tuple[bool, str]:
        if self.authenticate():
            return True, "Connected"
        return False, "Not connected"

