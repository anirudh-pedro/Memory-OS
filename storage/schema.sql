CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    sender TEXT,
    snippet TEXT,
    received_at TEXT
);

CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT UNIQUE,
    description TEXT,
    language TEXT,
    visibility TEXT,
    stars INTEGER,
    forks INTEGER,
    open_issues INTEGER,
    default_branch TEXT,
    updated_at TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS repository_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT,
    file_name TEXT,
    content TEXT,
    source TEXT,
    synced_at TEXT
);
