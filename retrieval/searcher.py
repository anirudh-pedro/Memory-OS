import sqlite3
import json
import logging
import re
from typing import List, Dict, Any
from core.db import DatabaseConnectionManager
from core.vector_store import QdrantVectorStore
from core.embeddings import BaseEmbedder
from core.graph_store import BaseGraphStore

logger = logging.getLogger(__name__)

class HybridSearcher:
    def __init__(self, db_manager: DatabaseConnectionManager, vector_store: QdrantVectorStore, embedder: BaseEmbedder, graph_store: BaseGraphStore):
        self.db_manager = db_manager
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store

    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize query string to prevent SQLite FTS5 MATCH syntax errors."""
        cleaned = re.sub(r'[^\w\s]', ' ', query)
        tokens = [t.strip() for t in cleaned.split() if t.strip()]
        return " ".join(tokens)

    def search_vector_store(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Perform semantic similarity search using query vectors and Qdrant client."""
        if not getattr(self.vector_store, "vector_retrieval_enabled", True):
            logger.warning("Vector retrieval mode is disabled. Skipping vector search.")
            return []

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
        """Search entities and their 1-hop relationships."""
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
                        "properties": json.loads(r["properties_json"] or "{}")
                    } for r in rows
                ]
        except sqlite3.Error:
            pass

        if not matched_nodes:
            try:
                cursor.execute(
                    "SELECT name, entity_type, description, properties_json FROM entities WHERE name LIKE ? OR description LIKE ? LIMIT ?",
                    (f"%{query}%", f"%{query}%", limit)
                )
                rows = cursor.fetchall()
                matched_nodes = [
                    {
                        "name": r["name"],
                        "entity_type": r["entity_type"],
                        "description": r["description"],
                        "properties": json.loads(r["properties_json"] or "{}")
                    } for r in rows
                ]
            except sqlite3.Error as e:
                logger.error(f"SQLite entity search failed: {e}")
            finally:
                conn.close()
        else:
            conn.close()

        all_relations = []
        for node in matched_nodes:
            try:
                relations = self.graph_store.get_multi_hop_relationships(node["name"], depth=1)
                all_relations.extend(relations)
            except Exception as e:
                logger.warning(f"Failed to fetch relationships for {node['name']}: {e}")

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

    def search_hybrid(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Perform unified hybrid search over vector and graph database."""
        vector_hits = self.search_vector_store(query, limit=limit)
        graph_hits = self.search_graph(query, limit=limit)
        return {
            "vector": vector_hits,
            "graph": graph_hits
        }
