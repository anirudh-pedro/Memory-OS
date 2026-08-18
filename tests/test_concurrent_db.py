"""
Tests for concurrent SQLite multi-threaded access safety.
"""

import os
import concurrent.futures
from unittest.mock import patch

from storage.db import (
    init_db,
    get_db_connection,
    insert_repository,
    get_repo_count,
    insert_document_chunks_batch,
    get_document_chunk_count
)
from models.memory import Repository


def test_concurrent_sqlite_writes(tmp_path):
    """Verify that multi-threaded writes via get_db_connection() do not deadlock or crash."""
    db_file = tmp_path / "concurrent_test.db"
    init_db(str(db_file))

    def write_repo(index):
        repo = Repository(
            repo_name=f"repo-{index}",
            description=f"Description {index}",
            language="Python",
            visibility="public",
            stars=index,
            forks=1,
            open_issues=0,
            default_branch="main",
            updated_at="2026-08-18T00:00:00",
            url=f"https://github.com/test/repo-{index}"
        )
        with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
            insert_repository(repo)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(write_repo, i) for i in range(30)]
        concurrent.futures.wait(futures)

    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
        assert get_repo_count() == 30


def test_concurrent_batch_chunk_inserts(tmp_path):
    """Verify concurrent batch chunk insertions across multiple threads."""
    db_file = tmp_path / "concurrent_chunks.db"
    init_db(str(db_file))

    def insert_batch(thread_id):
        chunks = [
            {
                "repository_name": f"repo-{thread_id}",
                "document_name": f"doc-{i}.md",
                "source_type": "document",
                "chunk_text": f"Content from thread {thread_id} chunk {i}",
                "chunk_index": i,
                "created_at": "2026-08-18T00:00:00"
            }
            for i in range(20)
        ]
        with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
            insert_document_chunks_batch(chunks)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(insert_batch, t) for t in range(5)]
        concurrent.futures.wait(futures)

    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
        assert get_document_chunk_count() == 100
