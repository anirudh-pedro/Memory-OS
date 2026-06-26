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
        return GraphStore._driver

    @property
    def is_fallback(self) -> bool:
        return GraphStore._use_fallback

    def close(self):
        if GraphStore._driver:
            try:
                GraphStore._driver.close()
            except Exception:
                pass
            GraphStore._driver = None

    def clear_graph(self):
        if self.is_fallback:
            clear_fallback_graph()
            return

        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def insert_node(self, node_id: str, label: str, name: str):
        if self.is_fallback:
            insert_fallback_node(node_id, label, name)
            return

        with self.driver.session() as session:
            query = f"MERGE (n:{label} {{id: $id}}) SET n.name = $name"
            session.run(query, id=node_id, name=name)

    def insert_relationship(self, rel_id: str, source_id: str, source_label: str, target_id: str, target_label: str, rel_type: str):
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

    def extract_and_sync_graph(self):
        """Extract entities and relationships from SQLite and sync them to Neo4j/Fallback Graph."""
        print("Extracting entities and relationships to Graph...")
        self.clear_graph()

        # 1. Repositories and detected technologies
        repos = get_all_repositories()
        for repo in repos:
            repo_name = repo["repo_name"]
            repo_node_id = f"Repository:{repo_name}"
            self.insert_node(repo_node_id, "Repository", repo_name)
            
            # Detect technology
            techs = detect_tech_for_repo(repo_name)
            for tech in techs:
                tech_node_id = f"Technology:{tech}"
                self.insert_node(tech_node_id, "Technology", tech)
                
                # Relationship USES
                rel_id = f"{repo_name}-USES-{tech}"
                self.insert_relationship(rel_id, repo_node_id, "Repository", tech_node_id, "Technology", "USES")

        # 2. Documents inside repositories
        docs = get_all_documents()
        for doc in docs:
            repo_name = doc["repo_name"]
            file_name = doc["file_name"]
            
            doc_node_id = f"Document:{repo_name}:{file_name}"
            self.insert_node(doc_node_id, "Document", file_name)
            
            repo_node_id = f"Repository:{repo_name}"
            # Relationship CONTAINS
            rel_id = f"{repo_name}-CONTAINS-{file_name}"
            self.insert_relationship(rel_id, repo_node_id, "Repository", doc_node_id, "Document", "CONTAINS")

        # 3. Emails and senders
        emails = get_all_emails()
        for email in emails:
            subject = email["subject"] or "No Subject"
            sender = email["sender"] or "Unknown Sender"
            message_id = email["message_id"] or ""
            
            email_node_id = f"Email:{message_id}"
            self.insert_node(email_node_id, "Email", subject)
            
            user_node_id = f"User:{sender}"
            self.insert_node(user_node_id, "User", sender)
            
            # Relationship SENT_BY
            rel_id = f"{message_id}-SENT_BY-{sender}"
            self.insert_relationship(rel_id, email_node_id, "Email", user_node_id, "User", "SENT_BY")

        print("Graph sync complete.")
