from abc import ABC, abstractmethod
import sqlite3
import json
import logging

logger = logging.getLogger(__name__)

class BaseGraphManager(ABC):
    @abstractmethod
    def add_node(self, entity_type: str, name: str, properties: dict = None) -> int:
        """Add a node (entity) to the graph. Returns the node ID."""
        pass

    @abstractmethod
    def get_node(self, name: str) -> dict:
        """Get a node's details by its unique name."""
        pass

    @abstractmethod
    def add_relationship(self, source_name: str, target_name: str, relation_type: str) -> bool:
        """Create a directed relationship (edge) between two nodes by their names."""
        pass

    @abstractmethod
    def get_relationships(self, entity_name: str) -> list:
        """Get direct relationships (1-hop) for a specific entity name."""
        pass

    @abstractmethod
    def get_multi_hop_relationships(self, entity_name: str, depth: int = 2) -> list:
        """Get multi-hop relationships (up to depth N) starting from a specific entity."""
        pass

    @abstractmethod
    def get_all_nodes(self) -> list:
        """Retrieve all nodes in the graph."""
        pass

    @abstractmethod
    def get_all_relationships(self) -> list:
        """Retrieve all edges (relationships) in the graph."""
        pass

    @abstractmethod
    def clear_graph(self) -> None:
        """Clear all nodes and relationships."""
        pass


class SQLiteGraphManager(BaseGraphManager):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_schema(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, name TEXT NOT NULL UNIQUE, properties_json TEXT DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS relationships (id INTEGER PRIMARY KEY AUTOINCREMENT, source_entity_id INTEGER NOT NULL, target_entity_id INTEGER NOT NULL, relation_type TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(source_entity_id) REFERENCES entities(id) ON DELETE CASCADE, FOREIGN KEY(target_entity_id) REFERENCES entities(id) ON DELETE CASCADE, UNIQUE(source_entity_id, target_entity_id, relation_type))")
        conn.commit()
        conn.close()

    def add_node(self, entity_type: str, name: str, properties: dict = None) -> int:
        properties = properties or {}
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # 1. Entity Resolution: Check case-insensitively for an existing node
            cursor.execute("SELECT id, name, properties_json FROM entities WHERE LOWER(name) = LOWER(?)", (name,))
            row = cursor.fetchone()
            if row:
                # Merge properties and keep the original casing
                resolved_name = row['name']
                existing_props = json.loads(row['properties_json'])
                existing_props.update(properties)
                cursor.execute(
                    "UPDATE entities SET entity_type = ?, properties_json = ? WHERE id = ?",
                    (entity_type, json.dumps(existing_props), row['id'])
                )
                node_id = row['id']
                logger.info(f"Resolved entity '{name}' to existing node '{resolved_name}' and merged properties.")
            else:
                cursor.execute(
                    "INSERT INTO entities (entity_type, name, properties_json) VALUES (?, ?, ?)",
                    (entity_type, name, json.dumps(properties))
                )
                node_id = cursor.lastrowid
            conn.commit()
            return node_id
        except sqlite3.Error as e:
            logger.error(f"Failed to add node {name}: {e}")
            raise e
        finally:
            conn.close()

    def get_node(self, name: str) -> dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE LOWER(name) = LOWER(?)", (name,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "id": row["id"],
                "entity_type": row["entity_type"],
                "name": row["name"],
                "properties": json.loads(row["properties_json"]),
                "created_at": row["created_at"]
            }
        return None

    def add_relationship(self, source_name: str, target_name: str, relation_type: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Look up case-insensitively using entity resolution
            cursor.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (source_name,))
            src_row = cursor.fetchone()
            cursor.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (target_name,))
            tgt_row = cursor.fetchone()

            if not src_row or not tgt_row:
                logger.warning(f"Could not build relationship. Source '{source_name}' or Target '{target_name}' not found.")
                return False

            src_id = src_row['id']
            tgt_id = tgt_row['id']

            cursor.execute(
                "INSERT OR IGNORE INTO relationships (source_entity_id, target_entity_id, relation_type) VALUES (?, ?, ?)",
                (src_id, tgt_id, relation_type.upper())
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to add relationship {source_name} -> {relation_type} -> {target_name}: {e}")
            return False
        finally:
            conn.close()

    def get_relationships(self, entity_name: str) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (entity_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return []
        
        ent_id = row['id']
        cursor.execute(
            """
            SELECT r.relation_type, e_src.name AS source, e_tgt.name AS target
            FROM relationships r
            JOIN entities e_src ON r.source_entity_id = e_src.id
            JOIN entities e_tgt ON r.target_entity_id = e_tgt.id
            WHERE r.source_entity_id = ? OR r.target_entity_id = ?
            """,
            (ent_id, ent_id)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "relation_type": r["relation_type"],
                "source": r["source"],
                "target": r["target"]
            } for r in rows
        ]

    def get_multi_hop_relationships(self, entity_name: str, depth: int = 2) -> list:
        """Query multi-hop relationships up to depth N using a recursive SQL Common Table Expression (CTE)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # 1. Finds all nodes within N hops
            # 2. Joins the nodes to get all relationships connecting them
            cursor.execute(
                """
                WITH RECURSIVE graph_path(entity_id, path_length) AS (
                    SELECT id, 0 FROM entities WHERE LOWER(name) = LOWER(?)
                    UNION
                    SELECT CASE WHEN r.source_entity_id = gp.entity_id THEN r.target_entity_id ELSE r.source_entity_id END, gp.path_length + 1
                    FROM relationships r
                    JOIN graph_path gp ON r.source_entity_id = gp.entity_id OR r.target_entity_id = gp.entity_id
                    WHERE gp.path_length < ?
                )
                SELECT DISTINCT r.relation_type, e_src.name AS source, e_tgt.name AS target
                FROM relationships r
                JOIN entities e_src ON r.source_entity_id = e_src.id
                JOIN entities e_tgt ON r.target_entity_id = e_tgt.id
                JOIN graph_path gp ON r.source_entity_id = gp.entity_id OR r.target_entity_id = gp.entity_id
                """,
                (entity_name, depth)
            )
            rows = cursor.fetchall()
            return [
                {
                    "relation_type": r["relation_type"],
                    "source": r["source"],
                    "target": r["target"]
                } for r in rows
            ]
        except sqlite3.Error as e:
            logger.error(f"Multi-hop recursive query failed: {e}")
            return self.get_relationships(entity_name)
        finally:
            conn.close()

    def get_all_nodes(self) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities")
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "entity_type": r["entity_type"],
                "name": r["name"],
                "properties": json.loads(r["properties_json"]),
                "created_at": r["created_at"]
            } for r in rows
        ]

    def get_all_relationships(self) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.id, e_src.name AS source, e_tgt.name AS target, r.relation_type, r.created_at
            FROM relationships r
            JOIN entities e_src ON r.source_entity_id = e_src.id
            JOIN entities e_tgt ON r.target_entity_id = e_tgt.id
            """
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "source": r["source"],
                "target": r["target"],
                "relation_type": r["relation_type"],
                "created_at": r["created_at"]
            } for r in rows
        ]

    def clear_graph(self) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM relationships")
        cursor.execute("DELETE FROM entities")
        conn.commit()
        conn.close()


class Neo4jGraphManager(BaseGraphManager):
    def __init__(self, uri: str, user: str = "neo4j", password: str = None):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_schema()

    def _ensure_schema(self):
        # Create a unique constraint on entity name to implement entity resolution in Neo4j
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT UNIQUE_ENTITY_NAME IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")

    def add_node(self, entity_type: str, name: str, properties: dict = None) -> int:
        properties = properties or {}
        properties_json = json.dumps(properties)
        query = (
            "MERGE (e:Entity {name: $name}) "
            "ON CREATE SET e.entity_type = $entity_type, e.properties = $properties_json "
            "ON MATCH SET e.properties = apoc.map.merge(coalesce(e.properties, '{}'), $properties_json) "
            "RETURN id(e) AS id"
        )
        # Fallback if apoc is not available
        fallback_query = (
            "MERGE (e:Entity {name: $name}) "
            "ON CREATE SET e.entity_type = $entity_type, e.properties = $properties_json "
            "ON MATCH SET e.properties = $properties_json "
            "RETURN id(e) AS id"
        )
        with self.driver.session() as session:
            try:
                res = session.run(query, name=name, entity_type=entity_type, properties_json=properties_json)
                record = res.single()
                return record["id"]
            except Exception:
                res = session.run(fallback_query, name=name, entity_type=entity_type, properties_json=properties_json)
                record = res.single()
                return record["id"]

    def get_node(self, name: str) -> dict:
        query = "MATCH (e:Entity {name: $name}) RETURN id(e) AS id, e.entity_type AS entity_type, e.name AS name, e.properties AS properties"
        with self.driver.session() as session:
            res = session.run(query, name=name)
            record = res.single()
            if record:
                return {
                    "id": record["id"],
                    "entity_type": record["entity_type"],
                    "name": record["name"],
                    "properties": json.loads(record["properties"])
                }
        return None

    def add_relationship(self, source_name: str, target_name: str, relation_type: str) -> bool:
        relation_type = relation_type.upper().replace(" ", "_")
        # In Cypher, relationship type cannot be parameterized, so we format it safely.
        query = (
            f"MATCH (a:Entity {{name: $source_name}}), (b:Entity {{name: $target_name}}) "
            f"MERGE (a)-[r:{relation_type}]->(b) "
            f"RETURN id(r) AS id"
        )
        with self.driver.session() as session:
            res = session.run(query, source_name=source_name, target_name=target_name)
            record = res.single()
            return record is not None

    def get_relationships(self, entity_name: str) -> list:
        return self.get_multi_hop_relationships(entity_name, depth=1)

    def get_multi_hop_relationships(self, entity_name: str, depth: int = 2) -> list:
        # Retrieve all connections up to depth N
        query = (
            f"MATCH path = (a:Entity {{name: $name}})-[*1..{depth}]-(b:Entity) "
            "UNWIND relationships(path) AS r "
            "RETURN DISTINCT startNode(r).name AS source, endNode(r).name AS target, type(r) AS relation_type"
        )
        with self.driver.session() as session:
            res = session.run(query, name=entity_name)
            return [
                {
                    "source": record["source"],
                    "target": record["target"],
                    "relation_type": record["relation_type"]
                } for record in res
            ]

    def get_all_nodes(self) -> list:
        query = "MATCH (e:Entity) RETURN id(e) AS id, e.entity_type AS entity_type, e.name AS name, e.properties AS properties"
        with self.driver.session() as session:
            res = session.run(query)
            return [
                {
                    "id": r["id"],
                    "entity_type": r["entity_type"],
                    "name": r["name"],
                    "properties": json.loads(r["properties"])
                } for r in res
            ]

    def get_all_relationships(self) -> list:
        query = "MATCH (a:Entity)-[r]->(b:Entity) RETURN id(r) AS id, a.name AS source, b.name AS target, type(r) AS relation_type"
        with self.driver.session() as session:
            res = session.run(query)
            return [
                {
                    "id": r["id"],
                    "source": r["source"],
                    "target": r["target"],
                    "relation_type": r["relation_type"]
                } for r in res
            ]

    def clear_graph(self) -> None:
        query = "MATCH (n) DETACH DELETE n"
        with self.driver.session() as session:
            session.run(query)

    def close(self):
        self.driver.close()
