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
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)
    conn.commit()
    conn.close()

def insert_repository(repo):
    conn = get_connection()
    cursor = conn.cursor()
    # Check if a repository with the same name already exists to avoid duplicates
    cursor.execute("SELECT id FROM repositories WHERE repo_name = ?", (repo.repo_name,))
    row = cursor.fetchone()
    if row:
        cursor.execute(
            """
            UPDATE repositories 
            SET description = ?, language = ?, url = ?, last_updated = ?
            WHERE id = ?
            """,
            (repo.description, repo.language, repo.url, repo.last_updated, row[0])
        )
    else:
        cursor.execute(
            """
            INSERT INTO repositories (repo_name, description, language, url, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            (repo.repo_name, repo.description, repo.language, repo.url, repo.last_updated)
        )
    conn.commit()
    conn.close()

def insert_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    # Check if an email with the same subject, sender, and timestamp exists
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

def get_email_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM emails")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def clear_all():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM repositories")
    cursor.execute("DELETE FROM emails")
    conn.commit()
    conn.close()
