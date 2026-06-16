import sqlite3
import json
import logging
import re
from memory.graph_manager import BaseGraphManager
from memory.embeddings import LocalTFIDFEmbedder

logger = logging.getLogger(__name__)

class RetrievalEngine:
    def __init__(self, db_path: str, graph_manager: BaseGraphManager, qdrant_client = None):
        self.db_path = db_path
        self.graph_manager = graph_manager
        self.qdrant_client = qdrant_client
        self.embedder = None
        self._setup_fts()
        if self.qdrant_client:
            self.initialize_vector_index()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _setup_fts(self):
        # Double check virtual tables exist for FTS5 queries
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS workspace_cache_fts USING fts5(
                    title,
                    content,
                    content='workspace_cache',
                    content_rowid='id'
                )
                """
            )
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
                    name,
                    content='entities',
                    content_rowid='id'
                )
                """
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"FTS5 setup warning (may already exist or not supported): {e}")
        finally:
            conn.close()

    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize query string to prevent SQLite FTS5 MATCH syntax errors."""
        # Strip all punctuation except spaces and letters/digits
        cleaned = re.sub(r'[^\w\s]', ' ', query)
        tokens = [t.strip() for t in cleaned.split() if t.strip()]
        return " ".join(tokens)

    def initialize_vector_index(self):
        """Build TF-IDF vocabulary on all cached items & entities, and index them in Qdrant."""
        if not self.qdrant_client:
            return
        
        logger.info("Initializing local Qdrant vector index...")
        try:
            # 1. Fetch all documents to fit the embedder
            documents = []
            payloads = []
            
            # Fetch cache items
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT source_app, external_id, title, content FROM workspace_cache")
            cache_rows = cursor.fetchall()
            conn.close()
            
            for row in cache_rows:
                title = row["title"] or ""
                content = row["content"] or ""
                doc_text = f"{title} {content}"
                documents.append(doc_text)
                payloads.append({
                    "type": "workspace_cache",
                    "source_app": row["source_app"],
                    "external_id": row["external_id"],
                    "title": title,
                    "content": content
                })
                
            # Fetch graph nodes
            nodes = self.graph_manager.get_all_nodes()
            for node in nodes:
                name = node["name"] or ""
                entity_type = node["entity_type"] or ""
                props = json.dumps(node["properties"] or {})
                doc_text = f"{name} {entity_type} {props}"
                documents.append(doc_text)
                payloads.append({
                    "type": "graph_node",
                    "name": name,
                    "entity_type": entity_type,
                    "properties": node["properties"]
                })
                
            if not documents:
                # Placeholder to avoid empty vocabulary
                documents = ["Placeholder workspace doc"]
                payloads.append({
                    "type": "placeholder",
                    "title": "Placeholder",
                    "content": "Placeholder workspace doc"
                })
                
            # 2. Fit TF-IDF embedder
            self.embedder = LocalTFIDFEmbedder()
            self.embedder.fit(documents)
            dimension = len(self.embedder.vocabulary)
            if dimension == 0:
                dimension = 1
                
            logger.info(f"Qdrant index dimension defined by vocab size: {dimension}")
            
            # 3. Create or recreate Qdrant collection without using deprecated recreate_collection
            from qdrant_client.models import Distance, VectorParams, PointStruct
            
            collection_name = "memory_os"
            if self.qdrant_client.collection_exists(collection_name):
                self.qdrant_client.delete_collection(collection_name)
            
            self.qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
            )
            
            # 4. Embed documents and upsert
            vectors = self.embedder.embed_documents(documents)
            points = []
            for i, (vector, payload) in enumerate(zip(vectors, payloads)):
                points.append(
                    PointStruct(
                        id=i,
                        vector=vector,
                        payload=payload
                    )
                )
                
            if points:
                self.qdrant_client.upsert(
                    collection_name=collection_name,
                    points=points
                )
                logger.info(f"Successfully indexed {len(points)} items in local Qdrant.")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant vector index: {e}")

    def search_workspace_cache(self, query: str, limit: int = 5) -> list:
        """Perform Full-Text Search (FTS5) across cached workspace data (GitHub, Notion, etc.)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            conn.close()
            return []
            
        try:
            # Query the virtual FTS table linked to workspace_cache
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
            # Truncate content length to 1000 characters to protect context window size limit
            return [
                {
                    "source_app": r["source_app"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "content": r["content"][:1000] + ("..." if len(r["content"]) > 1000 else "")
                } for r in rows
            ]
        except sqlite3.Error as e:
            logger.error(f"FTS5 workspace search failed: {e}. Falling back to LIKE query.")
            # Fallback to standard LIKE queries in case FTS is unindexed
            cursor.execute(
                """
                SELECT source_app, external_id, title, content
                FROM workspace_cache
                WHERE title LIKE ? OR content LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit)
            )
            rows = cursor.fetchall()
            return [
                {
                    "source_app": r["source_app"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "content": r["content"][:1000] + ("..." if len(r["content"]) > 1000 else "")
                } for r in rows
            ]
        finally:
            conn.close()

    def search_graph(self, query: str, limit: int = 5) -> dict:
        """Search Graph Nodes (FTS5) and fetch their multi-hop relationships (depth=2)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        matched_nodes = []
        sanitized = self._sanitize_fts_query(query)
        
        try:
            if sanitized:
                cursor.execute(
                    """
                    SELECT e.name, e.entity_type, e.properties_json
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
                        "properties": json.loads(r["properties_json"])
                    } for r in rows
                ]
            else:
                matched_nodes = []
        except sqlite3.Error:
            # Fallback LIKE
            cursor.execute(
                "SELECT name, entity_type, properties_json FROM entities WHERE name LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            )
            rows = cursor.fetchall()
            matched_nodes = [
                {
                    "name": r["name"],
                    "entity_type": r["entity_type"],
                    "properties": json.loads(r["properties_json"])
                } for r in rows
            ]
        finally:
            conn.close()

        # For each matched node, fetch its multi-hop graph relationships (depth=2)
        all_relations = []
        for node in matched_nodes:
            relations = self.graph_manager.get_multi_hop_relationships(node["name"], depth=2)
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
            "relationships": unique_relations
        }

    def search_conversations(self, query: str, limit: int = 5) -> list:
        """Retrieve recent conversation logs containing match criteria."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT thread_id, role, content, created_at FROM messages WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit)
            )
            rows = cursor.fetchall()
            return [
                {
                    "thread_id": r["thread_id"],
                    "role": r["role"],
                    "content": r["content"],
                    "created_at": r["created_at"]
                } for r in rows
            ]
        finally:
            conn.close()

    def search_vector_store(self, query: str, limit: int = 5) -> list:
        """Perform semantic similarity search using local Qdrant collection query_points and TF-IDF Embeddings."""
        if not self.qdrant_client or not self.embedder:
            return []
        try:
            logger.info(f"Querying local Qdrant vector store for: '{query}'")
            query_vector = self.embedder.embed_query(query)
            
            # Use query_points instead of deprecated search method
            response = self.qdrant_client.query_points(
                collection_name="memory_os",
                query=query_vector,
                limit=limit
            )
            
            matches = []
            for hit in response.points:
                payload = hit.payload
                score = hit.score
                if payload.get("type") == "workspace_cache":
                    content_trunc = payload['content'][:1000] + ("..." if len(payload['content']) > 1000 else "")
                    matches.append(f"[{payload['source_app'].upper()} (similarity: {score:.2f})] {payload['title']}: {content_trunc}")
                elif payload.get("type") == "graph_node":
                    matches.append(f"[Graph Node '{payload['name']}' ({payload['entity_type']}) (similarity: {score:.2f})] Details: {json.dumps(payload['properties'])}")
            return matches
        except Exception as e:
            logger.warning(f"Qdrant vector search failed: {e}")
            return []

    def build_context(self, query: str) -> str:
        """Search across all layers and build a clean context prompt block with a strict character budget."""
        cache_results = self.search_workspace_cache(query)
        graph_results = self.search_graph(query)
        message_results = self.search_conversations(query)
        vector_results = self.search_vector_store(query)

        context_lines = []
        char_budget = 2500  # Strict character budget (~600 tokens) to guarantee no rate/token limit errors on LLM (leaving safe room for tools & conversation history)
        
        # 1. Cached App Details
        if cache_results:
            section_lines = ["=== WORKSPACE CACHE MATCHES ==="]
            for item in cache_results:
                item_lines = [
                    f"[{item['source_app'].upper()}] {item['title']}",
                    f"Content: {item['content']}",
                    "-" * 20
                ]
                section_lines.extend(item_lines)
            
            section_text = "\n".join(section_lines)
            if len(section_text) > char_budget:
                section_text = section_text[:char_budget] + "\n... [Workspace Cache truncated due to context limits] ..."
            context_lines.append(section_text)
            char_budget -= len(section_text)
            
        # 2. Semantic Nodes & Graph
        if char_budget > 1000 and (graph_results["entities"] or graph_results["relationships"]):
            section_lines = ["\n=== KNOWLEDGE GRAPH MEMORY ==="]
            if graph_results["entities"]:
                section_lines.append("Entities:")
                for ent in graph_results["entities"]:
                    section_lines.append(f"- {ent['name']} ({ent['entity_type']}) - Details: {json.dumps(ent['properties'])}")
            if graph_results["relationships"]:
                section_lines.append("Relationships:")
                for rel in graph_results["relationships"]:
                    section_lines.append(f"- ({rel['source']}) -- {rel['relation_type']} --> ({rel['target']})")
            
            section_text = "\n".join(section_lines)
            if len(section_text) > char_budget:
                section_text = section_text[:char_budget] + "\n... [Knowledge Graph truncated due to context limits] ..."
            context_lines.append(section_text)
            char_budget -= len(section_text)
            
        # 3. Message Matches
        if char_budget > 1000 and message_results:
            section_lines = ["\n=== PAST CONVERSATION MATCHES ==="]
            for msg in message_results:
                section_lines.append(f"[{msg['created_at']}] {msg['role'].upper()}: {msg['content']}")
            
            section_text = "\n".join(section_lines)
            if len(section_text) > char_budget:
                section_text = section_text[:char_budget] + "\n... [Conversation history truncated] ..."
            context_lines.append(section_text)
            char_budget -= len(section_text)

        # 4. Vector Matches
        if char_budget > 1000 and vector_results:
            section_lines = ["\n=== SEMANTIC VECTOR MATCHES ==="]
            for v in vector_results:
                section_lines.append(f"- {v}")
            
            section_text = "\n".join(section_lines)
            if len(section_text) > char_budget:
                section_text = section_text[:char_budget] + "\n... [Vector matches truncated] ..."
            context_lines.append(section_text)
            char_budget -= len(section_text)

        return "\n".join(context_lines) if context_lines else "No relevant context found in memory."
