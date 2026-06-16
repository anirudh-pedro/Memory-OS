import logging
import base64
from memory.memory_manager import WorkspaceCacheRepository

logger = logging.getLogger(__name__)

def sync_github(session, cache_repo: WorkspaceCacheRepository) -> int:
    """Sync GitHub profile, projects, repositories, readmes, issues, and PRs.
    Saves to local workspace cache. Returns count of synced items.
    """
    logger.info("Starting Deep GitHub sync...")
    count = 0
    username = None
    
    # 1. Get the authenticated user
    try:
        user_resp = session.execute(
            tool_slug="github_get_the_authenticated_user",
            arguments={}
        )
        if user_resp.error:
            logger.error(f"Failed to get authenticated user details: {user_resp.error}")
        else:
            user_data = user_resp.data
            username = user_data.get("login")
            user_id = str(user_data.get("id", ""))
            name = user_data.get("name") or username or "Unknown"
            
            bio = user_data.get("bio") or ""
            email = user_data.get("email") or ""
            html_url = user_data.get("html_url") or ""
            
            content = f"User Profile: {name} (@{username})\nEmail: {email}\nURL: {html_url}\nBio: {bio}"
            
            success = cache_repo.upsert_cache(
                source_app="github",
                external_id=f"user_{user_id}",
                title=f"[GitHub User] {name}",
                content=content,
                metadata=user_data
            )
            if success:
                count += 1
    except Exception as e:
        logger.error(f"Error fetching user profile: {e}")

    # 2. Get User Projects V2 (requires username)
    if username:
        try:
            projects_resp = session.execute(
                tool_slug="github_list_user_projects",
                arguments={"username": username}
            )
            if projects_resp.error:
                logger.warning(f"Could not fetch user projects: {projects_resp.error}")
            else:
                projects_list = projects_resp.data.get("root", [])
                for proj in projects_list:
                    if not isinstance(proj, dict):
                        continue
                    proj_id = str(proj.get("id", ""))
                    proj_title = proj.get("title", "Untitled Project")
                    proj_url = proj.get("url", "")
                    proj_desc = proj.get("shortDescription", "") or ""
                    
                    content = f"Project V2: {proj_title}\nURL: {proj_url}\nDescription: {proj_desc}"
                    success = cache_repo.upsert_cache(
                        source_app="github",
                        external_id=f"project_{proj_id}",
                        title=f"[GitHub Project] {proj_title}",
                        content=content,
                        metadata=proj
                    )
                    if success:
                        count += 1
        except Exception as e:
            logger.error(f"Error fetching user projects: {e}")

    # 3. Get Repositories
    try:
        response = session.execute(
            tool_slug="github_list_repositories_for_the_authenticated_user",
            arguments={}
        )
        
        if not response or response.error:
            logger.error(f"GitHub sync list repos error: {response.error if response else 'No response'}")
            return count
            
        repos = response.data.get("repositories", [])
        if not isinstance(repos, list):
            logger.warning("No repositories list returned in data.")
            return count

        for repo in repos:
            if not isinstance(repo, dict):
                continue
            repo_id = str(repo.get("id", ""))
            name = repo.get("name", "")
            owner_login = repo.get("owner", {}).get("login", "")
            full_name = repo.get("full_name", f"{owner_login}/{name}")
            html_url = repo.get("html_url", "")
            description = repo.get("description", "") or ""
            language = repo.get("language", "") or ""
            open_issues_count = repo.get("open_issues_count", 0)
            
            repo_content = f"Repository: {full_name}\nURL: {html_url}\nLanguage: {language}\nDescription: {description}\nOpen Issues: {open_issues_count}"
            
            success = cache_repo.upsert_cache(
                source_app="github",
                external_id=f"repo_{repo_id}",
                title=f"[GitHub Repo] {full_name}",
                content=repo_content,
                metadata=repo
            )
            if success:
                count += 1

            # Fetch README for this repo
            try:
                readme_resp = session.execute(
                    tool_slug="github_get_a_repository_readme",
                    arguments={"owner": owner_login, "repo": name}
                )
                if not readme_resp.error and readme_resp.data:
                    readme_content = readme_resp.data.get("content", "")
                    encoding = readme_resp.data.get("encoding", "")
                    if encoding == "base64" and readme_content:
                        try:
                            decoded = base64.b64decode(readme_content.strip()).decode("utf-8", errors="ignore")
                            success_readme = cache_repo.upsert_cache(
                                source_app="github",
                                external_id=f"readme_{repo_id}",
                                title=f"[GitHub README] {full_name}",
                                content=decoded,
                                metadata={"repo_id": repo_id, "full_name": full_name}
                            )
                            if success_readme:
                                count += 1
                        except Exception as decode_err:
                            logger.warning(f"Failed to decode base64 readme for {full_name}: {decode_err}")
            except Exception as e:
                logger.warning(f"Could not sync README for {full_name}: {e}")

            # Fetch Open Issues for this repo
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
                        body = issue.get("body", "") or ""
                        author = issue.get("user", {}).get("login", "")
                        state = issue.get("state", "open")
                        
                        is_pr = "pull_request" in issue
                        prefix = "PR" if is_pr else "Issue"
                        
                        issue_content = f"{prefix} #{number} in {full_name}\nTitle: {title}\nAuthor: {author}\nState: {state}\n\nBody:\n{body}"
                        
                        success_issue = cache_repo.upsert_cache(
                            source_app="github",
                            external_id=f"issue_{issue_id}",
                            title=f"[GitHub {prefix} #{number}] {full_name}: {title}",
                            content=issue_content,
                            metadata=issue
                        )
                        if success_issue:
                            count += 1
            except Exception as e:
                logger.warning(f"Could not sync issues for {full_name}: {e}")

            # Fetch Open Pull Requests for this repo
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
                        body = pr.get("body", "") or ""
                        author = pr.get("user", {}).get("login", "")
                        state = pr.get("state", "open")
                        
                        pr_content = f"PR #{number} in {full_name}\nTitle: {title}\nAuthor: {author}\nState: {state}\n\nBody:\n{body}"
                        
                        success_pr = cache_repo.upsert_cache(
                            source_app="github",
                            external_id=f"pr_{pr_id}",
                            title=f"[GitHub PR #{number}] {full_name}: {title}",
                            content=pr_content,
                            metadata=pr
                        )
                        if success_pr:
                            count += 1
            except Exception as e:
                logger.warning(f"Could not sync PRs for {full_name}: {e}")
                
        logger.info(f"Successfully synced {count} total items from GitHub.")
        return count
    except Exception as e:
        logger.error(f"Failed to sync GitHub: {e}")
        return count
