import sqlite3
import os

DB_PATH = "memory.db"
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    # Check if repositories table exists and needs recreation (e.g. legacy schema)
    cursor.execute("PRAGMA table_info(repositories)")
    columns = [row[1] for row in cursor.fetchall()]
    if columns and "visibility" not in columns:
        cursor.execute("DROP TABLE repositories")
        cursor.execute("DROP TABLE IF EXISTS repository_documents")
        
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)
    conn.commit()
    conn.close()

def insert_repository(repo):
    conn = get_connection()
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
    conn.commit()
    conn.close()

def insert_repository_document(doc):
    conn = get_connection()
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
    conn.commit()
    conn.close()

def insert_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM emails WHERE subject = ? AND sender = ? AND received_at = ?",
        (email.subject, email.sender, email.received_at)
    )
    row = cursor.fetchone()
    if row:
        cursor.execute(
            "UPDATE emails SET snippet = ? WHERE id = ?",
            (email.snippet, row[0])
        )
    else:
        cursor.execute(
            "INSERT INTO emails (subject, sender, snippet, received_at) VALUES (?, ?, ?, ?)",
            (email.subject, email.sender, email.snippet, email.received_at)
        )
    conn.commit()
    conn.close()

def get_repo_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM repositories")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_repository_document_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM repository_documents")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_email_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM emails")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_repository_details(repo_name: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT repo_name, description, language, visibility, stars, forks, open_issues, default_branch, updated_at, url FROM repositories WHERE repo_name = ?",
        (repo_name,)
    )
    repo_row = cursor.fetchone()
    if not repo_row:
        conn.close()
        return None
    
    # Get files stored for this repository
    cursor.execute(
        "SELECT file_name FROM repository_documents WHERE repo_name = ?",
        (repo_name,)
    )
    files = [row[0] for row in cursor.fetchall()]
    
    # Get README content
    cursor.execute(
        "SELECT content FROM repository_documents WHERE repo_name = ? AND file_name = 'README.md'",
        (repo_name,)
    )
    readme_row = cursor.fetchone()
    readme_content = readme_row[0] if readme_row else None
    
    conn.close()
    return {
        "repo_name": repo_row[0],
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM repositories")
    cursor.execute("DELETE FROM repository_documents")
    cursor.execute("DELETE FROM emails")
    conn.commit()
    conn.close()
