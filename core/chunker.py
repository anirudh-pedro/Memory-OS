import datetime
from storage.db import (
    get_all_repositories,
    get_all_documents,
    get_all_emails,
    insert_document_chunk,
    clear_document_chunks
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
    from storage.db import get_connection
    created_at = datetime.datetime.now().isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    if repo_names is None:
        clear_document_chunks()
        
        # 1. Repositories (Metadata Chunks for identity search boosting)
        repos = get_all_repositories()
        for repo in repos:
            repo_text = f"Repository: {repo['repo_name']}\nDescription: {repo['description'] or ''}\nLanguage: {repo['language'] or ''}"
            # Insert repository metadata as a distinct source type to avoid mixing with document content
            insert_document_chunk(
                repository_name=repo["repo_name"],
                document_name="metadata",
                source_type="repository_metadata",
                chunk_text=repo_text,
                chunk_index=0,
                created_at=created_at
            )
            
        # 2. Repository Documents
        docs = get_all_documents()
        for doc in docs:
            content = doc["content"] or ""
            chunks = chunk_text(content)
            for idx, chunk in enumerate(chunks):
                insert_document_chunk(
                    repository_name=doc["repo_name"],
                    document_name=doc["file_name"],
                    source_type="document",
                    chunk_text=chunk,
                    chunk_index=idx,
                    created_at=created_at
                )
                
        # 3. Emails
        emails = get_all_emails()
        for email in emails:
            email_text = f"Subject: {email['subject']}\nFrom: {email['sender']}\nDate: {email['received_at']}\nContent: {email['snippet']}"
            chunks = chunk_text(email_text)
            for idx, chunk in enumerate(chunks):
                insert_document_chunk(
                    repository_name=None,
                    document_name=email["subject"] or email["message_id"],
                    source_type="email",
                    chunk_text=chunk,
                    chunk_index=idx,
                    created_at=created_at
                )
    else:
        # Incremental sync for specific repositories or emails
        for r_name in repo_names:
            if r_name == "__emails__":
                # Delete existing email chunks
                cursor.execute("DELETE FROM document_chunks WHERE source_type = 'email'")
                conn.commit()
                # Insert email chunks
                emails = get_all_emails()
                for email in emails:
                    email_text = f"Subject: {email['subject']}\nFrom: {email['sender']}\nDate: {email['received_at']}\nContent: {email['snippet']}"
                    chunks = chunk_text(email_text)
                    for idx, chunk in enumerate(chunks):
                        insert_document_chunk(
                            repository_name=None,
                            document_name=email["subject"] or email["message_id"],
                            source_type="email",
                            chunk_text=chunk,
                            chunk_index=idx,
                            created_at=created_at
                        )
            else:
                # Delete existing metadata and doc chunks for this repo
                cursor.execute(
                    "DELETE FROM document_chunks WHERE repository_name = ? AND source_type IN ('document', 'repository_metadata')",
                    (r_name,)
                )
                conn.commit()
                
                # Insert repo metadata chunk
                cursor.execute("SELECT repo_name, description, language FROM repositories WHERE repo_name = ?", (r_name,))
                repo_row = cursor.fetchone()
                if repo_row:
                    repo_text = f"Repository: {repo_row[0]}\nDescription: {repo_row[1] or ''}\nLanguage: {repo_row[2] or ''}"
                    insert_document_chunk(
                        repository_name=repo_row[0],
                        document_name="metadata",
                        source_type="repository_metadata",
                        chunk_text=repo_text,
                        chunk_index=0,
                        created_at=created_at
                    )
                
                # Insert repo document chunks
                cursor.execute("SELECT repo_name, file_name, content FROM repository_documents WHERE repo_name = ?", (r_name,))
                doc_rows = cursor.fetchall()
                for d_row in doc_rows:
                    content = d_row[2] or ""
                    chunks = chunk_text(content)
                    for idx, chunk in enumerate(chunks):
                        insert_document_chunk(
                            repository_name=d_row[0],
                            document_name=d_row[1],
                            source_type="document",
                            chunk_text=chunk,
                            chunk_index=idx,
                            created_at=created_at
                        )
    conn.close()

