"""
Load and stress tests for Memory-OS chunking, ranking, and storage subsystems.
"""

import time
import os
from unittest.mock import patch

from core.chunker import chunk_text
from core.ranking import RankingEngine
from storage.db import (
    init_db,
    insert_document_chunks_batch,
    get_document_chunk_count,
    search_local_knowledge_ranked
)


def test_chunker_large_document_stress():
    """Stress test chunk_text with a large 1MB document."""
    paragraph = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 20
    large_text = paragraph * 1000  # ~1.1 MB text
    
    start = time.perf_counter()
    chunks = chunk_text(large_text, chunk_size=800, overlap=120)
    duration = time.perf_counter() - start
    
    assert len(chunks) > 1000
    assert duration < 1.0, f"Chunking 1MB text took too long: {duration:.2f}s"


def test_ranking_engine_large_candidate_stress():
    """Stress test RankingEngine scoring across 5,000 candidates."""
    query_terms = ["python", "machine", "learning", "database", "vector"]
    graph_results = ["Repository 'repo-100' USES Technology 'Python'"]
    
    start = time.perf_counter()
    scores = []
    for i in range(5000):
        s = RankingEngine.calculate_score(
            semantic_sim=0.75,
            repo_name=f"repo-{i}",
            file_name=f"file_{i}.py",
            candidate_type="document",
            repo_filter="repo-100",
            graph_results=graph_results,
            search_text=f"Sample Python machine learning document content {i}",
            query_terms=query_terms,
            is_repo_focused=False
        )
        scores.append(s)
    duration = time.perf_counter() - start
    
    assert len(scores) == 5000
    assert duration < 1.0, f"Ranking 5000 candidates took too long: {duration:.2f}s"


def test_batch_insertion_large_repo_stress(tmp_path):
    """Stress test batch chunk insertion for a repository with 1,000 chunks."""
    db_file = tmp_path / "stress_repo.db"
    init_db(str(db_file))
    
    chunks = [
        {
            "repository_name": "large-monorepo",
            "document_name": f"src/module_{i//10}/file_{i}.py",
            "source_type": "document",
            "chunk_text": f"def function_{i}():\n    return {i} * 42\n",
            "chunk_index": i % 10,
            "created_at": "2026-08-18T00:00:00"
        }
        for i in range(1000)
    ]
    
    start = time.perf_counter()
    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}):
        insert_document_chunks_batch(chunks)
        count = get_document_chunk_count()
    duration = time.perf_counter() - start
    
    assert count == 1000
    assert duration < 2.0, f"Batch inserting 1000 chunks took too long: {duration:.2f}s"
