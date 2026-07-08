import os
import logging
from neo4j import GraphDatabase
from storage.db import (
    insert_fallback_node,
    insert_fallback_relationship,
    get_fallback_relationships,
    clear_fallback_graph,
    get_all_repositories,
    get_all_documents,
    get_all_emails,
    get_connection
)
from storage.tech_detector import detect_tech_for_repo

logger = logging.getLogger("graph_store")

class GraphStore:
    _driver = None
    _use_fallback = False

    def __init__(self):
        """Initialise driver for Neo4j knowledge graph, falling back to local SQLite if unavailable."""
        if GraphStore._driver is None and not GraphStore._use_fallback:
            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "password")
            
            try:
                driver = GraphDatabase.driver(uri, auth=(user, password))
                driver.verify_connectivity()
                GraphStore._driver = driver
                logger.info("Connected to Neo4j database successfully.")
                print("Neo4j connection successful.")
            except Exception as e:
                GraphStore._use_fallback = True
                logger.warning(f"Neo4j connectivity check failed: {e}. Falling back to SQLite graph storage.")
                print("Neo4j not available. Using local SQLite Graph storage.")

    @property
    def driver(self):
        """Get the active Neo4j driver client instance."""
        return GraphStore._driver

    @property
    def is_fallback(self) -> bool:
        """Boolean flag indicating whether the SQLite fallback graph engine is active."""
        return GraphStore._use_fallback

    def close(self):
        """Close the active Neo4j driver connection cleanly."""
        if GraphStore._driver:
            try:
                GraphStore._driver.close()
            except Exception:
                pass
            GraphStore._driver = None

    def clear_graph(self):
        """Delete all nodes and relationships from both active and fallback graphs."""
        if self.is_fallback:
            clear_fallback_graph()
            return

        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def insert_node(self, node_id: str, label: str, name: str):
        """Merge a new node with unique node_id and name into the graph database."""
        if self.is_fallback:
            insert_fallback_node(node_id, label, name)
            return

        with self.driver.session() as session:
            query = f"MERGE (n:{label} {{id: $id}}) SET n.name = $name"
            session.run(query, id=node_id, name=name)

    def insert_relationship(self, rel_id: str, source_id: str, source_label: str, target_id: str, target_label: str, rel_type: str):
        """Merge a new directed relationship of rel_type between source and target nodes."""
        if self.is_fallback:
            insert_fallback_relationship(rel_id, source_id, target_id, rel_type)
            return

        with self.driver.session() as session:
            query = (
                f"MATCH (s:{source_label} {{id: $source_id}}) "
                f"MATCH (t:{target_label} {{id: $target_id}}) "
                f"MERGE (s)-[r:{rel_type}]->(t) "
                f"SET r.id = $rel_id"
            )
            session.run(query, source_id=source_id, target_id=target_id, rel_id=rel_id)

    def lookup_relationships(self, entity_name: str) -> list:
        """Find nodes matching entity_name (case-insensitive substring) and return descriptions of their relationships."""
        descriptions = []
        entity_lower = entity_name.lower()

        if self.is_fallback:
            # First, find nodes in SQLite matching name
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, label, name FROM graph_nodes WHERE LOWER(name) LIKE ?", (f"%{entity_lower}%",))
            nodes = cursor.fetchall()
            conn.close()

            for node_id, label, name in nodes:
                rels = get_fallback_relationships(node_id)
                for r in rels:
                    desc = f"{r['source_label']} '{r['source_name']}' {r['type']} {r['target_label']} '{r['target_name']}'"
                    descriptions.append(desc)
            return list(set(descriptions))

        # Query Neo4j
        with self.driver.session() as session:
            query = (
                "MATCH (n) WHERE toLower(n.name) CONTAINS $entity "
                "MATCH (n)-[r]-(m) "
                "RETURN labels(n)[0] AS n_label, n.name AS n_name, type(r) AS rel_type, labels(m)[0] AS m_label, m.name AS m_name, startNode(r) = n AS is_outgoing"
            )
            result = session.run(query, entity=entity_lower)
            for record in result:
                n_label = record["n_label"] or "Node"
                n_name = record["n_name"] or ""
                rel_type = record["rel_type"] or ""
                m_label = record["m_label"] or "Node"
                m_name = record["m_name"] or ""
                
                if record["is_outgoing"]:
                    desc = f"{n_label} '{n_name}' {rel_type} {m_label} '{m_name}'"
                else:
                    desc = f"{m_label} '{m_name}' {rel_type} {n_label} '{n_name}'"
                descriptions.append(desc)
        return list(set(descriptions))

    def get_node_relationships(self, label: str, name: str) -> list:
        """Find relationships for a specific node by its label and name, case-insensitively."""
        descriptions = []
        name_lower = name.lower()

        if self.is_fallback:
            conn = get_connection()
            cursor = conn.cursor()
            # Find the node matching label and name case-insensitively
            cursor.execute(
                "SELECT id, label, name FROM graph_nodes WHERE LOWER(label) = LOWER(?) AND LOWER(name) = LOWER(?)",
                (label, name)
            )
            node = cursor.fetchone()
            if not node:
                # If exact name is not found, try containing it
                cursor.execute(
                    "SELECT id, label, name FROM graph_nodes WHERE LOWER(label) = LOWER(?) AND LOWER(name) LIKE ?",
                    (label, f"%{name_lower}%")
                )
                nodes = cursor.fetchall()
            else:
                nodes = [node]
                
            for node_id, n_lbl, n_nm in nodes:
                rels = get_fallback_relationships(node_id)
                for r in rels:
                    desc = f"{r['source_label']} '{r['source_name']}' {r['type']} {r['target_label']} '{r['target_name']}'"
                    descriptions.append(desc)
            conn.close()
            return list(set(descriptions))

        # Query Neo4j
        with self.driver.session() as session:
            query = (
                f"MATCH (n:{label}) WHERE toLower(n.name) = $name "
                "MATCH (n)-[r]-(m) "
                "RETURN labels(n)[0] AS n_label, n.name AS n_name, type(r) AS rel_type, labels(m)[0] AS m_label, m.name AS m_name, startNode(r) = n AS is_outgoing"
            )
            result = session.run(query, name=name_lower)
            records = list(result)
            if not records:
                query_contains = (
                    f"MATCH (n:{label}) WHERE toLower(n.name) CONTAINS $name "
                    "MATCH (n)-[r]-(m) "
                    "RETURN labels(n)[0] AS n_label, n.name AS n_name, type(r) AS rel_type, labels(m)[0] AS m_label, m.name AS m_name, startNode(r) = n AS is_outgoing"
                )
                result_contains = session.run(query_contains, name=name_lower)
                records = list(result_contains)

            for record in records:
                n_label = record["n_label"] or "Node"
                n_name = record["n_name"] or ""
                rel_type = record["rel_type"] or ""
                m_label = record["m_label"] or "Node"
                m_name = record["m_name"] or ""
                
                if record["is_outgoing"]:
                    desc = f"{n_label} '{n_name}' {rel_type} {m_label} '{m_name}'"
                else:
                    desc = f"{m_label} '{m_name}' {rel_type} {n_label} '{n_name}'"
                descriptions.append(desc)
        return list(set(descriptions))

    def extract_and_sync_graph(self, repo_names=None):
        """Extract entities and relationships from SQLite and sync them to Neo4j/Fallback Graph."""
        import time
        import logging
        logger = logging.getLogger("graph_store")
        
        logger.info("Starting graph synchronization process...")
        start_time = time.perf_counter()
        
        print("Extracting entities and relationships to Graph...")
        
        if repo_names is None:
            self.clear_graph()
        else:
            # Incremental clear
            for r_name in repo_names:
                if r_name == "__emails__":
                    if self.is_fallback:
                        from storage.db import get_connection
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM graph_relationships WHERE source_id LIKE 'Email:%' OR target_id LIKE 'Email:%' OR source_id LIKE 'User:%' OR target_id LIKE 'User:%'")
                        cursor.execute("DELETE FROM graph_nodes WHERE label IN ('Email', 'User')")
                        conn.commit()
                        conn.close()
                    else:
                        with self.driver.session() as session:
                            session.run("MATCH (e:Email) DETACH DELETE e")
                            session.run("MATCH (u:User) DETACH DELETE u")
                else:
                    repo_prefix = f"Document:{r_name}:"
                    repo_node_id = f"Repository:{r_name}"
                    if self.is_fallback:
                        from storage.db import get_connection
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "DELETE FROM graph_relationships WHERE source_id = ? OR target_id = ? OR source_id LIKE ? OR target_id LIKE ?",
                            (repo_node_id, repo_node_id, f"{repo_prefix}%", f"{repo_prefix}%")
                        )
                        cursor.execute(
                            "DELETE FROM graph_nodes WHERE id = ? OR id LIKE ?",
                            (repo_node_id, f"{repo_prefix}%")
                        )
                        conn.commit()
                        conn.close()
                    else:
                        with self.driver.session() as session:
                            session.run("MATCH (r:Repository {id: $repo_id}) DETACH DELETE r", repo_id=repo_node_id)
                            session.run("MATCH (d:Document) WHERE d.id STARTS WITH $prefix DETACH DELETE d", prefix=repo_prefix)

        node_count = 0
        rel_count = 0

        # Determine repos to sync
        if repo_names is None:
            repos_to_sync = get_all_repositories()
        else:
            all_repos = get_all_repositories()
            repos_to_sync = [r for r in all_repos if r["repo_name"] in repo_names]

        # 1. Repositories and detected technologies
        for repo in repos_to_sync:
            repo_name = repo["repo_name"]
            repo_node_id = f"Repository:{repo_name}"
            self.insert_node(repo_node_id, "Repository", repo_name)
            node_count += 1
            
            # Detect technology
            techs = detect_tech_for_repo(repo_name)
            for tech in techs:
                tech_node_id = f"Technology:{tech}"
                self.insert_node(tech_node_id, "Technology", tech)
                node_count += 1
                
                # Relationship USES
                rel_id = f"{repo_name}-USES-{tech}"
                self.insert_relationship(rel_id, repo_node_id, "Repository", tech_node_id, "Technology", "USES")
                rel_count += 1

        # 2. Documents inside repositories
        if repo_names is None:
            docs_to_sync = get_all_documents()
        else:
            all_docs = get_all_documents()
            docs_to_sync = [d for d in all_docs if d["repo_name"] in repo_names]

        for doc in docs_to_sync:
            repo_name = doc["repo_name"]
            file_name = doc["file_name"]
            
            doc_node_id = f"Document:{repo_name}:{file_name}"
            self.insert_node(doc_node_id, "Document", file_name)
            node_count += 1
            
            repo_node_id = f"Repository:{repo_name}"
            # Relationship CONTAINS
            rel_id = f"{repo_name}-CONTAINS-{file_name}"
            self.insert_relationship(rel_id, repo_node_id, "Repository", doc_node_id, "Document", "CONTAINS")
            rel_count += 1

        # 3. Emails and senders
        if repo_names is None or "__emails__" in repo_names:
            emails = get_all_emails()
            for email in emails:
                subject = email["subject"] or "No Subject"
                sender = email["sender"] or "Unknown Sender"
                message_id = email["message_id"] or ""
                
                email_node_id = f"Email:{message_id}"
                self.insert_node(email_node_id, "Email", subject)
                node_count += 1
                
                user_node_id = f"User:{sender}"
                self.insert_node(user_node_id, "User", sender)
                node_count += 1
                
                # Relationship SENT_BY
                rel_id = f"{message_id}-SENT_BY-{sender}"
                self.insert_relationship(rel_id, email_node_id, "Email", user_node_id, "User", "SENT_BY")
                rel_count += 1

        duration = time.perf_counter() - start_time
        target_db = "SQLite Fallback" if self.is_fallback else "Neo4j"
        logger.info(f"Graph sync complete. Synced to {target_db}. Nodes: {node_count}, Relationships: {rel_count} in {duration:.2f}s")
        print(f"Graph Sync Complete. Target: {target_db}. Nodes: {node_count}, Relationships: {rel_count}. Duration: {duration:.2f}s")
