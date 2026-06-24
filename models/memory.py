class Repository:
    def __init__(self, repo_name: str, description: str, language: str, visibility: str, stars: int, forks: int, open_issues: int, default_branch: str, updated_at: str, url: str):
        self.repo_name = repo_name
        self.description = description
        self.language = language
        self.visibility = visibility
        self.stars = stars
        self.forks = forks
        self.open_issues = open_issues
        self.default_branch = default_branch
        self.updated_at = updated_at
        self.url = url

class RepositoryDocument:
    def __init__(self, repo_name: str, file_name: str, content: str, source: str, synced_at: str):
        self.repo_name = repo_name
        self.file_name = file_name
        self.content = content
        self.source = source
        self.synced_at = synced_at

class Email:
    def __init__(self, subject: str, sender: str, snippet: str, received_at: str):
        self.subject = subject
        self.sender = sender
        self.snippet = snippet
        self.received_at = received_at
