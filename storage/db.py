import sqlite3
import os
import logging
import datetime
from contextlib import contextmanager

DB_PATH = "memory.db"
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
CURRENT_SCHEMA_VERSION = 1

_initialized_dbs = set()
logger = logging.getLogger("storage.db")


def _raw_connect(abs_path: str) -> sqlite3.Connection:
    """Open a raw SQLite connection ensuring the parent directory exists."""
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(abs_path)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db_schema(conn: sqlite3.Connection):
    """Apply base schema.sql file and initialize schema versioning."""
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO schema_versions (version, applied_at) VALUES (?, ?)",
        (CURRENT_SCHEMA_VERSION, datetime.datetime.now().isoformat())
    )
    conn.commit()


def _run_migrations(conn: sqlite3.Connection):
    """Run non-destructive incremental migrations on existing database tables."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()

    cursor.execute("SELECT MAX(version) FROM schema_versions")
    row = cursor.fetchone()
    current_ver = row[0] if (row and row[0] is not None) else 0

    # Migration 1: Check and non-destructively alter legacy tables if missing columns
    cursor.execute("PRAGMA table_info(repositories)")
    repo_cols = {r[1] for r in cursor.fetchall()}
    if repo_cols:
        for col_name, col_type in [
            ("visibility", "TEXT DEFAULT 'public'"),
            ("stars", "INTEGER DEFAULT 0"),
            ("forks", "INTEGER DEFAULT 0"),
            ("open_issues", "INTEGER DEFAULT 0"),
            ("default_branch", "TEXT DEFAULT 'main'"),
            ("updated_at", "TEXT"),
            ("url", "TEXT")
        ]:
            if col_name not in repo_cols:
                cursor.execute(f"ALTER TABLE repositories ADD COLUMN {col_name} {col_type}")

    cursor.execute("PRAGMA table_info(emails)")
    email_cols = {r[1] for r in cursor.fetchall()}
    if email_cols:
        if "message_id" not in email_cols:
            cursor.execute("ALTER TABLE emails ADD COLUMN message_id TEXT")

    if current_ver < 1:
        cursor.execute(
            "INSERT OR REPLACE INTO schema_versions (version, applied_at) VALUES (?, ?)",
            (1, datetime.datetime.now().isoformat())
        )
    conn.commit()


def _ensure_db_initialized(abs_path: str):
    """Internal helper to guarantee DB schema is initialized without calling get_connection()."""
    global _initialized_dbs
    if abs_path in _initialized_dbs:
        return

    conn = _raw_connect(abs_path)
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'")
            table_exists = cursor.fetchone()
        except sqlite3.OperationalError:
            table_exists = False

        if not table_exists:
            _init_db_schema(conn)
        else:
            _run_migrations(conn)
        _initialized_dbs.add(abs_path)
    finally:
        conn.close()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Return a raw SQLite connection for db_path (or MEMORY_OS_DB_PATH override).
    
    Guarantees initialization without circular dependencies.
    """
    if db_path is None:
        db_path = os.getenv("MEMORY_OS_DB_PATH", DB_PATH)
    abs_path = os.path.abspath(db_path)

    _ensure_db_initialized(abs_path)
    return _raw_connect(abs_path)


@contextmanager
def get_db_connection(db_path: str | None = None):
    """Context manager for SQLite connections. Automatically commits on success,
    rolls back on failure, and closes connection when block exits.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | None = None):
    """Explicitly initialize or migrate SQLite database schema."""
    if db_path is None:
        db_path = os.getenv("MEMORY_OS_DB_PATH", DB_PATH)
    abs_path = os.path.abspath(db_path)

    conn = _raw_connect(abs_path)
    try:
        _init_db_schema(conn)
        _run_migrations(conn)
        _initialized_dbs.add(abs_path)
    finally:
        conn.close()


def insert_repository(repo):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM repositories WHERE repo_name = ?", (repo.repo_name,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE repositories 
                SET description = ?, language = ?, visibility = ?, stars = ?, forks = ?, open_issues = ?, default_branch = ?, updated_at = ?, url = ?
                WHERE id = ?
                """,
                (repo.description, repo.language, repo.visibility, repo.stars, repo.forks, repo.open_issues, repo.default_branch, repo.updated_at, repo.url, row[0])
            )
        else:
            cursor.execute(
                """
                INSERT INTO repositories (repo_name, description, language, visibility, stars, forks, open_issues, default_branch, updated_at, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (repo.repo_name, repo.description, repo.language, repo.visibility, repo.stars, repo.forks, repo.open_issues, repo.default_branch, repo.updated_at, repo.url)
            )


def insert_repository_document(doc):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM repository_documents WHERE repo_name = ? AND file_name = ?",
            (doc.repo_name, doc.file_name)
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE repository_documents SET content = ?, source = ?, synced_at = ? WHERE id = ?",
                (doc.content, doc.source, doc.synced_at, row[0])
            )
        else:
            cursor.execute(
                "INSERT INTO repository_documents (repo_name, file_name, content, source, synced_at) VALUES (?, ?, ?, ?, ?)",
                (doc.repo_name, doc.file_name, doc.content, doc.source, doc.synced_at)
            )


def insert_email(email):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if email.message_id:
            cursor.execute("SELECT id FROM emails WHERE message_id = ?", (email.message_id,))
        else:
            cursor.execute(
                "SELECT id FROM emails WHERE subject = ? AND sender = ? AND received_at = ?",
                (email.subject, email.sender, email.received_at)
            )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE emails SET snippet = ?, subject = ?, sender = ?, received_at = ? WHERE id = ?",
                (email.snippet, email.subject, email.sender, email.received_at, row[0])
            )
        else:
            cursor.execute(
                "INSERT INTO emails (message_id, subject, sender, snippet, received_at) VALUES (?, ?, ?, ?, ?)",
                (email.message_id, email.subject, email.sender, email.snippet, email.received_at)
            )


def get_repo_count() -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM repositories")
        return cursor.fetchone()[0]


def get_repository_document_count() -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM repository_documents")
        return cursor.fetchone()[0]


def get_email_count() -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM emails")
        return cursor.fetchone()[0]


def get_repository_details(repo_name: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT repo_name, description, language, visibility, stars, forks, open_issues, default_branch, updated_at, url FROM repositories WHERE LOWER(repo_name) = LOWER(?)",
            (repo_name,)
        )
        repo_row = cursor.fetchone()
        if not repo_row:
            return None
        
        matched_name = repo_row[0]
        
        cursor.execute(
            "SELECT file_name FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)",
            (repo_name,)
        )
        files = [row[0] for row in cursor.fetchall()]
        
        cursor.execute(
            "SELECT content FROM repository_documents WHERE LOWER(repo_name) = LOWER(?) AND LOWER(file_name) = 'readme.md'",
            (repo_name,)
        )
        readme_row = cursor.fetchone()
        readme_content = readme_row[0] if readme_row else None
        
        return {
            "repo_name": matched_name,
            "description": repo_row[1],
            "language": repo_row[2],
            "visibility": repo_row[3],
            "stars": repo_row[4],
            "forks": repo_row[5],
            "open_issues": repo_row[6],
            "default_branch": repo_row[7],
            "updated_at": repo_row[8],
            "url": repo_row[9],
            "files": files,
            "readme": readme_content
        }


def clear_all():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM repositories")
        cursor.execute("DELETE FROM repository_documents")
        cursor.execute("DELETE FROM emails")
        cursor.execute("DELETE FROM document_chunks")
        cursor.execute("DELETE FROM graph_relationships")
        cursor.execute("DELETE FROM graph_nodes")


def search_local_knowledge_ranked(query: str, repo_filter: str = None) -> list:
    """Ranked search across repositories, documents, and emails."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if repo_filter:
            if isinstance(repo_filter, list):
                placeholders = ",".join(["?"] * len(repo_filter))
                cursor.execute(
                    f"SELECT repo_name, language, description FROM repositories WHERE LOWER(repo_name) IN ({placeholders})",
                    [r.lower() for r in repo_filter]
                )
                repos = cursor.fetchall()

                cursor.execute(
                    f"SELECT repo_name, file_name, content FROM repository_documents WHERE LOWER(repo_name) IN ({placeholders})",
                    [r.lower() for r in repo_filter]
                )
                docs = cursor.fetchall()
                emails = []
            else:
                cursor.execute("SELECT repo_name, language, description FROM repositories WHERE LOWER(repo_name) = LOWER(?)", (repo_filter,))
                repos = cursor.fetchall()

                cursor.execute("SELECT repo_name, file_name, content FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)", (repo_filter,))
                docs = cursor.fetchall()
                emails = []
        else:
            cursor.execute("SELECT repo_name, language, description FROM repositories")
            repos = cursor.fetchall()

            cursor.execute("SELECT repo_name, file_name, content FROM repository_documents")
            docs = cursor.fetchall()

            cursor.execute("SELECT subject, sender, snippet FROM emails")
            emails = cursor.fetchall()

    repo_boost = float(os.getenv('REPO_SCORE_BOOST', '1.0'))
    email_weight = float(os.getenv('EMAIL_SCORE_WEIGHT', '1.0'))

    ranked_results = []
    query_lower = query.lower()

    for repo_name, language, description in repos:
        score = 0
        if repo_name and query_lower in repo_name.lower():
            score += 10
        if description and query_lower in description.lower():
            score += 8
        if language and query_lower in language.lower():
            score += 5
        if score > 0:
            score = int(score * repo_boost)
            result = {
                "type": "repository",
                "score": score,
                "repo_name": repo_name,
                "language": language,
                "description": description,
                "source_type": "repository",
            }
            ranked_results.append(result)

    for repo_name, file_name, content in docs:
        score = 0
        content_lower = content.lower() if content else ""
        file_name_lower = file_name.lower() if file_name else ""
        if query_lower in file_name_lower or query_lower in content_lower:
            if file_name_lower == "readme.md":
                score += 6
            elif file_name_lower == "package.json":
                score += 4
            else:
                score += 3
        if score > 0:
            result = {
                "type": "document",
                "score": score,
                "repo_name": repo_name,
                "file_name": file_name,
                "content": content,
                "source_type": "document",
            }
            ranked_results.append(result)

    for subject, sender, snippet in emails:
        score = 0
        subj_l = subject.lower() if subject else ""
        send_l = sender.lower() if sender else ""
        snip_l = snippet.lower() if snippet else ""
        if query_lower in subj_l or query_lower in send_l or query_lower in snip_l:
            score += 2
        if score > 0:
            score = int(score * email_weight)
            result = {
                "type": "email",
                "score": score,
                "subject": subject,
                "sender": sender,
                "snippet": snippet,
                "source_type": "email",
            }
            ranked_results.append(result)

    ranked_results.sort(key=lambda x: (-x["score"], x.get("repo_name") or x.get("subject") or ""))
    return ranked_results


def get_all_repositories() -> list:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT repo_name, language, description, stars, forks, updated_at FROM repositories")
        return [
            {
                "repo_name": row[0],
                "language": row[1],
                "description": row[2],
                "stars": row[3],
                "forks": row[4],
                "updated_at": row[5]
            }
            for row in cursor.fetchall()
        ]


def get_all_documents() -> list:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT repo_name, file_name, content FROM repository_documents")
        return [
            {"repo_name": row[0], "file_name": row[1], "content": row[2]}
            for row in cursor.fetchall()
        ]


def insert_document_chunk(repository_name: str, document_name: str, source_type: str, chunk_text: str, chunk_index: int, created_at: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_chunks (repository_name, document_name, source_type, chunk_text, chunk_index, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (repository_name, document_name, source_type, chunk_text, chunk_index, created_at)
        )


def insert_document_chunks_batch(chunks: list[dict]):
    """Insert a list of document chunk dicts in a single batch transaction.
    
    Each item in chunks should be a dict with keys:
        repository_name, document_name, source_type, chunk_text, chunk_index, created_at
    """
    if not chunks:
        return
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO document_chunks (repository_name, document_name, source_type, chunk_text, chunk_index, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c.get("repository_name"),
                    c.get("document_name"),
                    c.get("source_type"),
                    c.get("chunk_text"),
                    c.get("chunk_index", 0),
                    c.get("created_at")
                )
                for c in chunks
            ]
        )


def clear_document_chunks():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM document_chunks")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'document_chunks'")


def get_document_chunk_count() -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM document_chunks")
        return cursor.fetchone()[0]


def get_all_document_chunks() -> list:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, repository_name, document_name, source_type, chunk_text, chunk_index FROM document_chunks")
        return [
            {
                "id": row[0],
                "repository_name": row[1],
                "document_name": row[2],
                "source_type": row[3],
                "chunk_text": row[4],
                "chunk_index": row[5]
            }
            for row in cursor.fetchall()
        ]


def get_all_emails() -> list:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT message_id, subject, sender, snippet, received_at FROM emails")
        return [
            {
                "message_id": row[0],
                "subject": row[1],
                "sender": row[2],
                "snippet": row[3],
                "received_at": row[4]
            }
            for row in cursor.fetchall()
        ]


def insert_fallback_node(node_id: str, label: str, name: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO graph_nodes (id, label, name) VALUES (?, ?, ?)",
            (node_id, label, name)
        )


def insert_fallback_relationship(rel_id: str, source_id: str, target_id: str, type_str: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO graph_relationships (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            (rel_id, source_id, target_id, type_str)
        )


def get_fallback_relationships(node_id: str) -> list:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.type, s.label, s.name, t.label, t.name
            FROM graph_relationships r
            JOIN graph_nodes s ON r.source_id = s.id
            JOIN graph_nodes t ON r.target_id = t.id
            WHERE r.source_id = ? OR r.target_id = ?
            """,
            (node_id, node_id)
        )
        return [
            {
                "type": row[0],
                "source_label": row[1],
                "source_name": row[2],
                "target_label": row[3],
                "target_name": row[4]
            }
            for row in cursor.fetchall()
        ]


def clear_fallback_graph():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM graph_relationships")
        cursor.execute("DELETE FROM graph_nodes")
