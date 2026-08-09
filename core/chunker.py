import datetime
from storage.db import (
    get_all_repositories,
    get_all_documents,
    get_all_emails,
    insert_document_chunks_batch,
    clear_document_chunks,
    get_db_connection
)

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= len(text):
            break
        start += chunk_size - overlap
    return chunks

def generate_and_save_chunks(repo_names=None):
    created_at = datetime.datetime.now().isoformat()
    chunks_to_insert = []
    
    if repo_names is None:
        clear_document_chunks()
        
        # 1. Repositories (Metadata Chunks for identity search boosting)
        repos = get_all_repositories()
        for repo in repos:
            repo_text = f"Repository: {repo['repo_name']}\nDescription: {repo['description'] or ''}\nLanguage: {repo['language'] or ''}"
            chunks_to_insert.append({
                "repository_name": repo["repo_name"],
                "document_name": "metadata",
                "source_type": "repository_metadata",
                "chunk_text": repo_text,
                "chunk_index": 0,
                "created_at": created_at
            })
            
        # 2. Repository Documents
        docs = get_all_documents()
        for doc in docs:
            content = doc["content"] or ""
            chunks = chunk_text(content)
            for idx, chunk in enumerate(chunks):
                chunks_to_insert.append({
                    "repository_name": doc["repo_name"],
                    "document_name": doc["file_name"],
                    "source_type": "document",
                    "chunk_text": chunk,
                    "chunk_index": idx,
                    "created_at": created_at
                })
                
        # 3. Emails
        emails = get_all_emails()
        for email in emails:
            email_text = f"Subject: {email['subject']}\nFrom: {email['sender']}\nDate: {email['received_at']}\nContent: {email['snippet']}"
            chunks = chunk_text(email_text)
            for idx, chunk in enumerate(chunks):
                chunks_to_insert.append({
                    "repository_name": None,
                    "document_name": email["subject"] or email["message_id"],
                    "source_type": "email",
                    "chunk_text": chunk,
                    "chunk_index": idx,
                    "created_at": created_at
                })

        insert_document_chunks_batch(chunks_to_insert)

    else:
        # Incremental sync for specific repositories or emails
        with get_db_connection() as conn:
            cursor = conn.cursor()
            for r_name in repo_names:
                if r_name == "__emails__":
                    cursor.execute("DELETE FROM document_chunks WHERE source_type = 'email'")
                    emails = get_all_emails()
                    email_chunks = []
                    for email in emails:
                        email_text = f"Subject: {email['subject']}\nFrom: {email['sender']}\nDate: {email['received_at']}\nContent: {email['snippet']}"
                        chunks = chunk_text(email_text)
                        for idx, chunk in enumerate(chunks):
                            email_chunks.append({
                                "repository_name": None,
                                "document_name": email["subject"] or email["message_id"],
                                "source_type": "email",
                                "chunk_text": chunk,
                                "chunk_index": idx,
                                "created_at": created_at
                            })
                    insert_document_chunks_batch(email_chunks)
                else:
                    cursor.execute(
                        "DELETE FROM document_chunks WHERE repository_name = ? AND source_type IN ('document', 'repository_metadata')",
                        (r_name,)
                    )
                    repo_chunks = []
                    cursor.execute("SELECT repo_name, description, language FROM repositories WHERE repo_name = ?", (r_name,))
                    repo_row = cursor.fetchone()
                    if repo_row:
                        repo_text = f"Repository: {repo_row[0]}\nDescription: {repo_row[1] or ''}\nLanguage: {repo_row[2] or ''}"
                        repo_chunks.append({
                            "repository_name": repo_row[0],
                            "document_name": "metadata",
                            "source_type": "repository_metadata",
                            "chunk_text": repo_text,
                            "chunk_index": 0,
                            "created_at": created_at
                        })
                    
                    cursor.execute("SELECT repo_name, file_name, content FROM repository_documents WHERE repo_name = ?", (r_name,))
                    doc_rows = cursor.fetchall()
                    for d_row in doc_rows:
                        content = d_row[2] or ""
                        chunks = chunk_text(content)
                        for idx, chunk in enumerate(chunks):
                            repo_chunks.append({
                                "repository_name": d_row[0],
                                "document_name": d_row[1],
                                "source_type": "document",
                                "chunk_text": chunk,
                                "chunk_index": idx,
                                "created_at": created_at
                            })
                    insert_document_chunks_batch(repo_chunks)
