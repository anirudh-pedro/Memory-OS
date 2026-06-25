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

def generate_and_save_chunks():
    clear_document_chunks()
    created_at = datetime.datetime.now().isoformat()
    
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
