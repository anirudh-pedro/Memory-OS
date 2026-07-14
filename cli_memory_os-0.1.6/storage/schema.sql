CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE,
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

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_name TEXT,
    document_name TEXT,
    source_type TEXT,
    chunk_text TEXT,
    chunk_index INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    label TEXT,
    name TEXT
);

CREATE TABLE IF NOT EXISTS graph_relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT,
    target_id TEXT,
    type TEXT,
    FOREIGN KEY(source_id) REFERENCES graph_nodes(id),
    FOREIGN KEY(target_id) REFERENCES graph_nodes(id)
);
