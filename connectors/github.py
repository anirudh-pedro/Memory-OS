import logging
import base64
from typing import List
from connectors.base import BaseConnector
from core.models import Memory

logger = logging.getLogger(__name__)

class GitHubConnector(BaseConnector):
    def sync(self, session) -> List[Memory]:
        """Fetch and normalize GitHub data into Memory objects."""
        logger.info("Starting GitHub memory sync...")
        memories = []
        username = None
        
        # 1. Authenticated User Profile
        try:
            user_resp = session.execute(tool_slug="github_get_the_authenticated_user", arguments={})
            if not user_resp.error and user_resp.data:
                user_data = user_resp.data
                username = user_data.get("login")
                user_id = str(user_data.get("id", ""))
                name = user_data.get("name") or username or "Unknown"
                
                content = (
                    f"User Profile: {name} (@{username})\n"
                    f"Email: {user_data.get('email') or ''}\n"
                    f"URL: {user_data.get('html_url') or ''}\n"
                    f"Bio: {user_data.get('bio') or ''}"
                )
                memories.append(
                    Memory(
                        source_app="github",
                        external_id=f"user_{user_id}",
                        title=f"[GitHub User] {name}",
                        content=content,
                        metadata_json=user_data
                    )
                )
        except Exception as e:
            logger.error(f"Error fetching user profile: {e}")

        # 2. User Projects
        if username:
            try:
                projects_resp = session.execute(tool_slug="github_list_user_projects", arguments={"username": username})
                if not projects_resp.error and projects_resp.data:
                    projects_list = projects_resp.data.get("root", [])
                    for proj in projects_list:
                        if not isinstance(proj, dict):
                            continue
                        proj_id = str(proj.get("id", ""))
                        title = proj.get("title", "Untitled Project")
                        content = f"Project V2: {title}\nURL: {proj.get('url', '')}\nDescription: {proj.get('shortDescription', '') or ''}"
                        memories.append(
                            Memory(
                                source_app="github",
                                external_id=f"project_{proj_id}",
                                title=f"[GitHub Project] {title}",
                                content=content,
                                metadata_json=proj
                            )
                        )
            except Exception as e:
                logger.error(f"Error fetching user projects: {e}")

        # 3. Repositories, READMEs, Issues, and PRs
        try:
            repo_resp = session.execute(tool_slug="github_list_repositories_for_the_authenticated_user", arguments={})
            if not repo_resp.error and repo_resp.data:
                repos = repo_resp.data.get("repositories", [])
                if isinstance(repos, list):
                    for repo in repos:
                        if not isinstance(repo, dict):
                            continue
                        repo_id = str(repo.get("id", ""))
                        name = repo.get("name", "")
                        owner_login = repo.get("owner", {}).get("login", "")
                        full_name = repo.get("full_name", f"{owner_login}/{name}")
                        description = repo.get("description", "") or ""
                        
                        repo_content = (
                            f"Repository: {full_name}\n"
                            f"URL: {repo.get('html_url', '')}\n"
                            f"Language: {repo.get('language', '') or ''}\n"
                            f"Description: {description}\n"
                            f"Open Issues: {repo.get('open_issues_count', 0)}"
                        )
                        memories.append(
                            Memory(
                                source_app="github",
                                external_id=f"repo_{repo_id}",
                                title=f"[GitHub Repo] {full_name}",
                                content=repo_content,
                                metadata_json=repo
                            )
                        )

                        # README
                        try:
                            readme_resp = session.execute(
                                tool_slug="github_get_a_repository_readme",
                                arguments={"owner": owner_login, "repo": name}
                            )
                            if not readme_resp.error and readme_resp.data:
                                readme_content = readme_resp.data.get("content", "")
                                encoding = readme_resp.data.get("encoding", "")
                                if encoding == "base64" and readme_content:
                                    decoded = base64.b64decode(readme_content.strip()).decode("utf-8", errors="ignore")
                                    memories.append(
                                        Memory(
                                            source_app="github",
                                            external_id=f"readme_{repo_id}",
                                            title=f"[GitHub README] {full_name}",
                                            content=decoded,
                                            metadata_json={"repo_id": repo_id, "full_name": full_name}
                                        )
                                    )
                        except Exception as e:
                            logger.warning(f"Could not sync README for {full_name}: {e}")

                        # Issues
                        try:
                            issues_resp = session.execute(
                                tool_slug="github_list_repository_issues",
                                arguments={"owner": owner_login, "repo": name, "state": "open", "per_page": 10}
                            )
                            if not issues_resp.error and issues_resp.data:
                                issues_list = issues_resp.data.get("issues", [])
                                for issue in issues_list:
                                    if not isinstance(issue, dict):
                                        continue
                                    issue_id = str(issue.get("id", ""))
                                    number = issue.get("number", "")
                                    title = issue.get("title", "")
                                    is_pr = "pull_request" in issue
                                    prefix = "PR" if is_pr else "Issue"
                                    
                                    issue_content = (
                                        f"{prefix} #{number} in {full_name}\n"
                                        f"Title: {title}\n"
                                        f"Author: {issue.get('user', {}).get('login', '')}\n"
                                        f"State: {issue.get('state', 'open')}\n\n"
                                        f"Body:\n{issue.get('body', '') or ''}"
                                    )
                                    memories.append(
                                        Memory(
                                            source_app="github",
                                            external_id=f"issue_{issue_id}",
                                            title=f"[GitHub {prefix} #{number}] {full_name}: {title}",
                                            content=issue_content,
                                            metadata_json=issue
                                        )
                                    )
                        except Exception as e:
                            logger.warning(f"Could not sync issues for {full_name}: {e}")

                        # PRs
                        try:
                            prs_resp = session.execute(
                                tool_slug="github_list_pull_requests",
                                arguments={"owner": owner_login, "repo": name, "state": "open", "per_page": 10}
                            )
                            if not prs_resp.error and prs_resp.data:
                                prs_list = prs_resp.data.get("pull_requests", [])
                                for pr in prs_list:
                                    if not isinstance(pr, dict):
                                        continue
                                    pr_id = str(pr.get("id", ""))
                                    number = pr.get("number", "")
                                    title = pr.get("title", "")
                                    
                                    pr_content = (
                                        f"PR #{number} in {full_name}\n"
                                        f"Title: {title}\n"
                                        f"Author: {pr.get('user', {}).get('login', '')}\n"
                                        f"State: {pr.get('state', 'open')}\n\n"
                                        f"Body:\n{pr.get('body', '') or ''}"
                                    )
                                    memories.append(
                                        Memory(
                                            source_app="github",
                                            external_id=f"pr_{pr_id}",
                                            title=f"[GitHub PR #{number}] {full_name}: {title}",
                                            content=pr_content,
                                            metadata_json=pr
                                        )
                                    )
                        except Exception as e:
                            logger.warning(f"Could not sync PRs for {full_name}: {e}")
        except Exception as e:
            logger.error(f"Failed to sync repositories: {e}")

        logger.info(f"Successfully normalized {len(memories)} GitHub memories.")
        return memories
