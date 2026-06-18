-- Enable foreign key support
PRAGMA foreign_keys = ON;

-- Conversational Messages Table
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);

-- Entities Table
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- Person, Project, Skill, Task, Event, Email, Repository, Document
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    aliases_json TEXT DEFAULT '[]',
    properties_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_entities_type_name ON entities(entity_type, name);

-- Relationships Table
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL, -- OWNS, USES, CREATED, ATTENDS, RELATED_TO, DEPENDS_ON, WORKS_ON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY(target_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    UNIQUE(source_entity_id, target_entity_id, relation_type)
);

-- Workspace Cache Table (For GitHub, Notion, Calendar, Gmail)
CREATE TABLE IF NOT EXISTS workspace_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_app TEXT NOT NULL, -- github, notion, googlecalendar, gmail
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_app, external_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_cache_app_ext ON workspace_cache(source_app, external_id);

-- FTS5 Full-Text Search Virtual Tables for Workspace Cache and Entities
CREATE VIRTUAL TABLE IF NOT EXISTS workspace_cache_fts USING fts5(
    title,
    content,
    content='workspace_cache',
    content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name,
    content='entities',
    content_rowid='id'
);

-- Triggers to automatically sync Workspace Cache and Entities into FTS5 tables
CREATE TRIGGER IF NOT EXISTS tgr_workspace_cache_ai AFTER INSERT ON workspace_cache BEGIN
    INSERT INTO workspace_cache_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS tgr_workspace_cache_ad AFTER DELETE ON workspace_cache BEGIN
    INSERT INTO workspace_cache_fts(workspace_cache_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS tgr_workspace_cache_au AFTER UPDATE ON workspace_cache BEGIN
    INSERT INTO workspace_cache_fts(workspace_cache_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
    INSERT INTO workspace_cache_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS tgr_entities_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name) VALUES (new.id, new.name);
END;

CREATE TRIGGER IF NOT EXISTS tgr_entities_ad AFTER DELETE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name) VALUES('delete', old.id, old.name);
END;

CREATE TRIGGER IF NOT EXISTS tgr_entities_au AFTER UPDATE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name) VALUES('delete', old.id, old.name);
    INSERT INTO entities_fts(rowid, name) VALUES (new.id, new.name);
END;
