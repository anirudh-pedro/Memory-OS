CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT,
    description TEXT,
    language TEXT,
    url TEXT,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    sender TEXT,
    snippet TEXT,
    received_at TEXT
);
