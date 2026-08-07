"""
Unit tests for core RAG pipeline: chunker, context_builder, LLM context prep, and vector store utilities.
"""

import unittest
from unittest.mock import patch, MagicMock

from core.chunker import chunk_text
from core.context_builder import ContextBuilder
from core.llm import prepare_rag_context, parse_rag_response, inject_repository_summary_chunk
from core.vector_store import compute_keyword_boost, detect_repo_in_query


class TestChunker(unittest.TestCase):
    """Test suite for text chunking functions."""

    def test_chunk_text_empty(self):
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text(None), [])

    def test_chunk_text_short(self):
        text = "Hello world"
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_chunk_text_splitting_and_overlap(self):
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        # chunk size 10, overlap 2 -> step 8
        chunks = chunk_text(text, chunk_size=10, overlap=2)
        self.assertTrue(len(chunks) > 1)
        self.assertEqual(chunks[0], "ABCDEFGHIJ")
        self.assertEqual(chunks[1], "IJKLMNOPQR")


class TestContextBuilder(unittest.TestCase):
    """Test suite for ContextBuilder classification, deduplication, scoring, and trimming."""

    def setUp(self):
        self.builder = ContextBuilder(max_context_chars=500, max_chunks=3)

    def test_classify_query_email(self):
        self.assertEqual(ContextBuilder.classify_query("check my email inbox"), "Email Question")

    def test_classify_query_tech(self):
        self.assertEqual(ContextBuilder.classify_query("which repositories use Python?"), "Technology Question")

    def test_classify_query_repo_filter(self):
        self.assertEqual(ContextBuilder.classify_query("what is in this repo?", repo_filter="my-repo"), "Repository Question")

    def test_classify_query_doc(self):
        self.assertEqual(ContextBuilder.classify_query("show me the README document"), "Documentation Question")

    def test_classify_query_cross(self):
        self.assertEqual(ContextBuilder.classify_query("list all my projects"), "Cross Repository Question")

    def test_estimate_tokens(self):
        self.assertEqual(self.builder.estimate_tokens("1234567890"), 2)

    def test_is_nearly_identical(self):
        text1 = "Python is a high level programming language used for machine learning"
        text2 = "Python is a high level programming language used for AI and machine learning"
        self.assertTrue(self.builder.is_nearly_identical(text1, text2))

        text3 = "JavaScript is used for web frontend development with React"
        self.assertFalse(self.builder.is_nearly_identical(text1, text3))

    def test_build_context_and_deduplication(self):
        vector_results = [
            {"source_type": "document", "repository_name": "RepoA", "document_name": "README.md", "chunk_text": "Content A", "score": 0.9},
            {"source_type": "document", "repository_name": "RepoA", "document_name": "README.md", "chunk_text": "Content A", "score": 0.85},
        ]
        keyword_results = []
        graph_results = []

        formatted_chunks, sources, repos, num_v, num_k, num_g, after_dedup = self.builder.build_context(
            "What is RepoA?", vector_results, keyword_results, graph_results
        )

        self.assertEqual(num_v, 2)
        self.assertEqual(after_dedup, 1)  # Duplicate filtered
        self.assertEqual(len(formatted_chunks), 1)
        self.assertIn("RepoA", repos)

    def test_trim_context_to_limit(self):
        system_prompt = "Sys"
        user_template = "{context}"
        chunks = [
            {"text": "Chunk 1 content " * 10, "score": 0.9, "type": "document"},
            {"text": "Chunk 2 content " * 10, "score": 0.3, "type": "document"},
        ]
        builder = ContextBuilder(max_prompt_tokens=10)
        merged, count = builder.trim_context_to_limit(system_prompt, user_template, chunks)
        self.assertTrue(count <= 1)


class TestLLMResponseParsing(unittest.TestCase):
    """Test suite for RAG response parsing and context preparation."""

    def test_parse_rag_response_success(self):
        llm_output = (
            "Answer: Memory-OS is a grounded PKOS.\n"
            "Sources: README.md, docs/arch.md\n"
            "Repositories Used: Memory-OS"
        )
        res = parse_rag_response(llm_output, ["fallback.md"], ["fallback-repo"])
        self.assertEqual(res["answer"], "Memory-OS is a grounded PKOS.")
        self.assertEqual(res["sources"], ["README.md", "docs/arch.md"])
        self.assertEqual(res["repositories"], ["Memory-OS"])
        self.assertEqual(res["confidence"], 0.9)

    def test_parse_rag_response_fallback(self):
        llm_output = "I couldn't find that information in the indexed knowledge."
        res = parse_rag_response(llm_output, ["fallback.md"], ["fallback-repo"])
        self.assertEqual(res["answer"], "I couldn't find that information in the indexed knowledge.")
        self.assertEqual(res["sources"], [])
        self.assertEqual(res["repositories"], [])
        self.assertEqual(res["confidence"], 0.0)

    @patch("storage.db.get_connection")
    def test_inject_repository_summary_chunk(self, mock_conn_fn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("RepoA", "Desc A", "Python")]
        mock_conn.cursor.return_value = mock_cursor
        mock_conn_fn.return_value = mock_conn

        chunks = [{"text": "Doc text", "score": 0.5, "type": "document"}]
        res = inject_repository_summary_chunk(list(chunks), "Cross Repository Question")
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["type"], "repository_summary")
        self.assertEqual(res[0]["score"], 999.0)


class TestVectorStoreUtilities(unittest.TestCase):
    """Test suite for keyword boosting and repository detection in queries."""

    def test_compute_keyword_boost(self):
        item = {
            "repository_name": "Memory-OS",
            "document_name": "README.md",
            "source_type": "document",
            "chunk_text": "Personal Knowledge Operating System"
        }
        boost = compute_keyword_boost(item, "Memory-OS README")
        self.assertTrue(boost > 0.5)

    @patch("storage.db.get_connection")
    def test_detect_repo_in_query(self, mock_conn_fn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("Memory-OS",), ("ai-agent",)]
        mock_conn.cursor.return_value = mock_cursor
        mock_conn_fn.return_value = mock_conn

        self.assertEqual(detect_repo_in_query("How does Memory-OS work?"), "Memory-OS")
        self.assertEqual(detect_repo_in_query("Tell me about ai agent"), "ai-agent")
        self.assertIsNone(detect_repo_in_query("What is Python?"))


if __name__ == "__main__":
    unittest.main()
