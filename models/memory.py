class Repository:
    def __init__(self, repo_name: str, description: str, language: str, url: str, last_updated: str):
        self.repo_name = repo_name
        self.description = description
        self.language = language
        self.url = url
        self.last_updated = last_updated

class Email:
    def __init__(self, subject: str, sender: str, snippet: str, received_at: str):
        self.subject = subject
        self.sender = sender
        self.snippet = snippet
        self.received_at = received_at
