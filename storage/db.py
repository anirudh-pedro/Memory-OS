import sqlite3
import os
import logging
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
        
    # Check if emails table exists and needs recreation (e.g. legacy schema without message_id)
    cursor.execute("PRAGMA table_info(emails)")
    email_columns = [row[1] for row in cursor.fetchall()]
    if email_columns and "message_id" not in email_columns:
        cursor.execute("DROP TABLE emails")
        
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
        "SELECT repo_name, description, language, visibility, stars, forks, open_issues, default_branch, updated_at, url FROM repositories WHERE LOWER(repo_name) = LOWER(?)",
        (repo_name,)
    )
    repo_row = cursor.fetchone()
    if not repo_row:
        conn.close()
        return None
    
    matched_name = repo_row[0]
    
    # Get files stored for this repository
    cursor.execute(
        "SELECT file_name FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)",
        (repo_name,)
    )
    files = [row[0] for row in cursor.fetchall()]
    
    # Get README content
    cursor.execute(
        "SELECT content FROM repository_documents WHERE LOWER(repo_name) = LOWER(?) AND LOWER(file_name) = 'readme.md'",
        (repo_name,)
    )
    readme_row = cursor.fetchone()
    readme_content = readme_row[0] if readme_row else None
    
    conn.close()
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM repositories")
    cursor.execute("DELETE FROM repository_documents")
    cursor.execute("DELETE FROM emails")
    cursor.execute("DELETE FROM document_chunks")
    conn.commit()
    conn.close()

def search_local_knowledge(query: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    q = f"%{query.lower()}%"
    
    # Search Repositories
    cursor.execute(
        """
        SELECT repo_name, language, description 
        FROM repositories 
        WHERE LOWER(repo_name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(language) LIKE ?
        """,
        (q, q, q)
    )
    repos = [
        {"repo_name": row[0], "language": row[1], "description": row[2]}
        for row in cursor.fetchall()
    ]
    
    # Search Documents
    cursor.execute(
        """
        SELECT repo_name, file_name, content 
        FROM repository_documents 
        WHERE LOWER(file_name) LIKE ? OR LOWER(content) LIKE ?
        """,
        (q, q)
    )
    docs = [
        {"repo_name": row[0], "file_name": row[1], "content": row[2]}
        for row in cursor.fetchall()
    ]
    
    # Search Emails
    cursor.execute(
        """
        SELECT subject, sender, snippet 
        FROM emails 
        WHERE LOWER(subject) LIKE ? OR LOWER(sender) LIKE ? OR LOWER(snippet) LIKE ?
        """,
        (q, q, q)
    )
    emails = [
        {"subject": row[0], "sender": row[1], "snippet": row[2]}
        for row in cursor.fetchall()
    ]
    
    conn.close()
    return {
        "repositories": repos,
        "documents": docs,
        "emails": emails
    }

def search_local_knowledge_ranked(query: str) -> list:
    """Ranked search across repositories, documents, and emails.

    Applies configurable boost for repository scores and weight for email scores.
    Adds ``source_type`` to each result and logs detailed diagnostics.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Fetch all data for scoring
    cursor.execute("SELECT repo_name, language, description FROM repositories")
    repos = cursor.fetchall()

    cursor.execute("SELECT repo_name, file_name, content FROM repository_documents")
    docs = cursor.fetchall()

    cursor.execute("SELECT subject, sender, snippet FROM emails")
    emails = cursor.fetchall()
    conn.close()

    # Configurable boosts (default = 1.0 i.e., no change)
    repo_boost = float(os.getenv('REPO_SCORE_BOOST', '1.0'))
    email_weight = float(os.getenv('EMAIL_SCORE_WEIGHT', '1.0'))

    ranked_results = []
    query_lower = query.lower()
    logger = logging.getLogger(__name__)

    # --- Score repositories ---
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
            logger.debug(f"Retrieval result - {result}")

    # --- Score documents ---
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
            logger.debug(f"Retrieval result - {result}")

    # --- Score emails ---
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
            logger.debug(f"Retrieval result - {result}")

    # Sort descending by score, then stable alphabetical tie‑breaker
    ranked_results.sort(key=lambda x: (-x["score"], x.get("repo_name") or x.get("subject") or ""))
    return ranked_results

    cursor = conn.cursor()
    
    # Fetch all for scoring
    cursor.execute("SELECT repo_name, language, description FROM repositories")
    repos = cursor.fetchall()
    
    cursor.execute("SELECT repo_name, file_name, content FROM repository_documents")
    docs = cursor.fetchall()
    
    cursor.execute("SELECT subject, sender, snippet FROM emails")
    emails = cursor.fetchall()
    conn.close()
    
    ranked_results = []
    query_lower = query.lower()
    
    # Score repositories
    for repo_name, language, description in repos:
        score = 0
        if repo_name and query_lower in repo_name.lower():
            score += 10 * repo_boost
        if description and query_lower in description.lower():
            score += 8 * repo_boost
        if language and query_lower in language.lower():
            score += 5 * repo_boost
            
        if score > 0:
            ranked_results.append({
                "type": "repository",
                "score": score,
                "repo_name": repo_name,
                "language": language,
                "description": description
            })
            
    # Score documents
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
            ranked_results.append({
                "type": "document",
                "score": score,
                "repo_name": repo_name,
                "file_name": file_name,
                "content": content
            })
            
    # Score emails
    for subject, sender, snippet in emails:
        score = 0
        subj_l = subject.lower() if subject else ""
        send_l = sender.lower() if sender else ""
        snip_l = snippet.lower() if snippet else ""
        if query_lower in subj_l or query_lower in send_l or query_lower in snip_l:
            score += 2 * email_weight
            
        if score > 0:
            ranked_results.append({
                "type": "email",
                "score": score,
                "subject": subject,
                "sender": sender,
                "snippet": snippet
            })
            
    # Sort descending by score, then alphabetically for stability
    ranked_results.sort(key=lambda x: (-x["score"], x.get("repo_name") or x.get("subject") or ""))
    return ranked_results

def get_repository_files(repo_name: str) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_name FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)", (repo_name,))
    files = [row[0] for row in cursor.fetchall()]
    conn.close()
    return files

def get_repository_readme(repo_name: str) -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM repository_documents WHERE LOWER(repo_name) = LOWER(?) AND LOWER(file_name) = 'readme.md'", (repo_name,))
    row = cursor.fetchone()
    readme = row[0] if row else None
    conn.close()
    return readme

def get_repository_summary_data(repo_name: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT repo_name, language, stars, forks, updated_at FROM repositories WHERE LOWER(repo_name) = LOWER(?)",
        (repo_name,)
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    
    matched_name = row[0]
    cursor.execute(
        "SELECT file_name FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)",
        (repo_name,)
    )
    files = [r[0] for r in cursor.fetchall()]
    conn.close()
    
    return {
        "repo_name": matched_name,
        "language": row[1],
        "stars": row[2],
        "forks": row[3],
        "updated_at": row[4],
        "documents_count": len(files),
        "files": files
    }

def get_all_repositories() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT repo_name, language, description, stars, forks, updated_at FROM repositories")
    repos = [
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
    conn.close()
    return repos

def get_all_documents() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT repo_name, file_name, content FROM repository_documents")
    docs = [
        {"repo_name": row[0], "file_name": row[1], "content": row[2]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return docs

def insert_document_chunk(repository_name: str, document_name: str, source_type: str, chunk_text: str, chunk_index: int, created_at: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO document_chunks (repository_name, document_name, source_type, chunk_text, chunk_index, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (repository_name, document_name, source_type, chunk_text, chunk_index, created_at)
    )
    conn.commit()
    conn.close()

def clear_document_chunks():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM document_chunks")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'document_chunks'")
    conn.commit()
    conn.close()

def get_document_chunk_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM document_chunks")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_document_chunks() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, repository_name, document_name, source_type, chunk_text, chunk_index FROM document_chunks")
    chunks = [
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
    conn.close()
    return chunks

def get_all_emails() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT message_id, subject, sender, snippet, received_at FROM emails")
    emails = [
        {
            "message_id": row[0],
            "subject": row[1],
            "sender": row[2],
            "snippet": row[3],
            "received_at": row[4]
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return emails
