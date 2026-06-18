import sqlite3
import json
import logging
import re
from typing import List, Dict, Any
from core.db import DatabaseConnectionManager
from core.vector_store import QdrantVectorStore
from core.embeddings import LocalTFIDFEmbedder
from core.graph_store import BaseGraphStore

logger = logging.getLogger(__name__)

class HybridSearcher:
    def __init__(self, db_manager: DatabaseConnectionManager, vector_store: QdrantVectorStore, embedder: LocalTFIDFEmbedder, graph_store: BaseGraphStore):
        self.db_manager = db_manager
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store

    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize query string to prevent SQLite FTS5 MATCH syntax errors."""
        cleaned = re.sub(r'[^\w\s]', ' ', query)
        tokens = [t.strip() for t in cleaned.split() if t.strip()]
        return " ".join(tokens)

    def search_workspace_cache(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Perform Full-Text Search (FTS5) across cached workspace data (GitHub, Notion, etc.)"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            conn.close()
            return []
            
        try:
            cursor.execute(
                """
                SELECT wc.id, wc.source_app, wc.external_id, wc.title, wc.content
                FROM workspace_cache_fts fts
                JOIN workspace_cache wc ON fts.rowid = wc.id
                WHERE fts.title MATCH ? OR fts.content MATCH ?
                LIMIT ?
                """,
                (sanitized, sanitized, limit)
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "source_app": r["source_app"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "content": r["content"][:1000] + ("..." if len(r["content"]) > 1000 else "")
                } for r in rows
            ]
        except sqlite3.Error as e:
            logger.warning(f"FTS5 workspace search failed: {e}. Falling back to LIKE query.")
            cursor.execute(
                """
                SELECT id, source_app, external_id, title, content
                FROM workspace_cache
                WHERE title LIKE ? OR content LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit)
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "source_app": r["source_app"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "content": r["content"][:1000] + ("..." if len(r["content"]) > 1000 else "")
                } for r in rows
            ]
        finally:
            conn.close()

    def search_vector_store(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Perform semantic similarity search using query vectors and Qdrant client."""
        vocab_size = len(self.embedder.vocabulary)
        if vocab_size == 0:
            logger.warning("Embedder vocabulary is empty. Skipping vector search.")
            return []
        try:
            query_vector = self.embedder.embed_query(query)
            return self.vector_store.search(query_vector, limit=limit)
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def search_graph(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Search entities and their multi-hop relationships (depth=2)."""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        matched_nodes = []
        sanitized = self._sanitize_fts_query(query)
        
        try:
            if sanitized:
                cursor.execute(
                    """
                    SELECT e.name, e.entity_type, e.description, e.properties_json
                    FROM entities_fts fts
                    JOIN entities e ON fts.rowid = e.id
                    WHERE fts.name MATCH ?
                    LIMIT ?
                    """,
                    (sanitized, limit)
                )
                rows = cursor.fetchall()
                matched_nodes = [
                    {
                        "name": r["name"],
                        "entity_type": r["entity_type"],
                        "description": r["description"],
                        "properties": json.loads(r["properties_json"])
                    } for r in rows
                ]
        except sqlite3.Error:
            cursor.execute(
                "SELECT name, entity_type, description, properties_json FROM entities WHERE name LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            )
            rows = cursor.fetchall()
            matched_nodes = [
                {
                    "name": r["name"],
                    "entity_type": r["entity_type"],
                    "description": r["description"],
                    "properties": json.loads(r["properties_json"])
                } for r in rows
            ]
        finally:
            conn.close()

        all_relations = []
        for node in matched_nodes:
            relations = self.graph_store.get_multi_hop_relationships(node["name"], depth=1)
            all_relations.extend(relations)

        # De-duplicate relationships
        unique_relations = []
        seen_rels = set()
        for r in all_relations:
            rel_key = (r["source"], r["target"], r["relation_type"])
            if rel_key not in seen_rels:
                seen_rels.add(rel_key)
                unique_relations.append(r)

        return {
            "entities": matched_nodes,
            "relationships": unique_relations[:15]  # Cap graph neighbors count to 15
        }
