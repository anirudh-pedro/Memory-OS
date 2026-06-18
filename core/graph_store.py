from abc import ABC, abstractmethod
import sqlite3
import json
import logging
from typing import List, Optional, Dict, Any
from core.models import Entity, Relationship

logger = logging.getLogger(__name__)

class BaseGraphStore(ABC):
    @abstractmethod
    def add_node(self, entity: Entity) -> int:
        """Add a node (entity) to the graph. Returns the node ID."""
        pass

    @abstractmethod
    def get_node(self, name: str) -> Optional[Entity]:
        """Get a node's details by its unique name."""
        pass

    @abstractmethod
    def add_relationship(self, relationship: Relationship) -> bool:
        """Create a directed relationship (edge) between two nodes."""
        pass

    @abstractmethod
    def get_relationships(self, entity_name: str) -> List[Dict[str, Any]]:
        """Get direct relationships (1-hop) for a specific entity name."""
        pass

    @abstractmethod
    def get_multi_hop_relationships(self, entity_name: str, depth: int = 2) -> List[Dict[str, Any]]:
        """Get multi-hop relationships (up to depth N) starting from a specific entity."""
        pass

    @abstractmethod
    def get_all_nodes(self) -> List[Entity]:
        """Retrieve all nodes in the graph."""
        pass

    @abstractmethod
    def get_all_relationships(self) -> List[Dict[str, Any]]:
        """Retrieve all edges (relationships) in the graph."""
        pass

    @abstractmethod
    def clear_graph(self) -> None:
        """Clear all nodes and relationships."""
        pass


import re

def is_valid_entity(entity: Entity) -> bool:
    """Validate entity name. Reject placeholders, generic artifacts, empty names, or generic prompt instructions."""
    # 1. Apply technology canonicalization override
    try:
        from memory.quality import TechnologyClassifier
        tech_canonical = TechnologyClassifier.classify(entity.name)
        if tech_canonical:
            entity.entity_type = "Technology"
            entity.name = tech_canonical
    except Exception:
        pass

    if entity.entity_type == "Repository":
        entity.name = entity.name.strip().lower()
        entity.aliases = [a.strip().lower() for a in entity.aliases]

    try:
        from memory.quality import EntityValidator
        return EntityValidator.is_valid(entity)
    except Exception:
        pass
    
    name = entity.name.strip()
    if not name:
        return False
    if len(name) <= 1 or name.isnumeric():
        return False
    return True


class SQLiteGraphStore(BaseGraphStore):
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                aliases_json TEXT DEFAULT '[]',
                properties_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id INTEGER NOT NULL,
                target_entity_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(source_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
                FOREIGN KEY(target_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
                UNIQUE(source_entity_id, target_entity_id, relation_type)
            )
            """
        )
        conn.commit()
        conn.close()

    def add_node(self, entity: Entity) -> int:
        if not is_valid_entity(entity):
            logger.info(f"Rejected invalid or placeholder entity node: '{entity.name}' ({entity.entity_type})")
            return -1

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Fetch all existing entities of same type to resolve alias matches
            cursor.execute("SELECT id, name, description, aliases_json, properties_json FROM entities WHERE entity_type = ?", (entity.entity_type,))
            rows = cursor.fetchall()
            
            matched_row = None
            for row in rows:
                row_name = row['name']
                row_aliases = json.loads(row['aliases_json'] or "[]")
                # Case-insensitive direct match
                if row_name.lower() == entity.name.lower():
                    matched_row = row
                    break
                # Case-insensitive alias list match
                if entity.name.lower() in [a.lower() for a in row_aliases]:
                    matched_row = row
                    break

            # If Repository and not matched yet, check flat-vs-full path relationships
            if not matched_row and entity.entity_type == "Repository":
                if "/" not in entity.name:
                    for row in rows:
                        row_name = row['name']
                        if "/" in row_name and row_name.lower().endswith(f"/{entity.name.lower()}"):
                            matched_row = row
                            break
                else:
                    flat_name = entity.name.split("/")[-1]
                    for row in rows:
                        row_name = row['name']
                        if "/" not in row_name and row_name.lower() == flat_name.lower():
                            matched_row = row
                            break

            if matched_row:
                node_id = matched_row['id']
                existing_name = matched_row['name']
                existing_aliases = json.loads(matched_row['aliases_json'] or "[]")
                existing_props = json.loads(matched_row['properties_json'] or "{}")
                
                # Merge properties
                existing_props.update(entity.properties)
                
                # Merge description
                new_desc = matched_row['description'] or ""
                if entity.description and entity.description not in new_desc:
                    new_desc = f"{new_desc}\n{entity.description}".strip()
                
                # Canonical name resolution:
                final_name = existing_name
                if entity.entity_type == "Repository":
                    final_name = final_name.lower()
                    if "/" in entity.name and "/" not in existing_name:
                        final_name = entity.name.lower()
                        if existing_name not in existing_aliases:
                            existing_aliases.append(existing_name)
                        logger.info(f"Canonical name promoted to repo full_name: '{final_name}' (old canonical: '{existing_name}')")
                
                # Add aliases
                if entity.name.lower() != final_name.lower() and entity.name not in existing_aliases:
                    existing_aliases.append(entity.name)
                for alias in entity.aliases:
                    if alias.lower() != final_name.lower() and alias not in existing_aliases:
                        existing_aliases.append(alias)

                cursor.execute(
                    "UPDATE entities SET name = ?, description = ?, aliases_json = ?, properties_json = ? WHERE id = ?",
                    (final_name, new_desc, json.dumps(existing_aliases), json.dumps(existing_props), node_id)
                )
                logger.info(f"Resolved entity '{entity.name}' to canonical node '{final_name}' and updated properties/aliases.")
            else:
                # No match, insert new node
                aliases_to_save = entity.aliases.copy()
                if entity.name not in aliases_to_save:
                    aliases_to_save.append(entity.name)
                cursor.execute(
                    "INSERT INTO entities (entity_type, name, description, aliases_json, properties_json) VALUES (?, ?, ?, ?, ?)",
                    (entity.entity_type, entity.name, entity.description, json.dumps(aliases_to_save), json.dumps(entity.properties))
                )
                node_id = cursor.lastrowid
                logger.info(f"Created new canonical node: '{entity.name}' ({entity.entity_type})")
            
            conn.commit()
            return node_id
        except sqlite3.Error as e:
            logger.error(f"Failed to add node {entity.name}: {e}")
            raise e
        finally:
            conn.close()

    def get_node(self, name: str) -> Optional[Entity]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE LOWER(name) = LOWER(?)", (name,))
        row = cursor.fetchone()
        
        # If not matched directly by name, scan aliases
        if not row:
            cursor.execute("SELECT * FROM entities")
            all_rows = cursor.fetchall()
            for r in all_rows:
                aliases = json.loads(r["aliases_json"] or "[]")
                if name.lower() in [a.lower() for a in aliases]:
                    row = r
                    break

        conn.close()
        if row:
            return Entity(
                name=row["name"],
                entity_type=row["entity_type"],
                description=row["description"],
                aliases=json.loads(row["aliases_json"] or "[]"),
                properties=json.loads(row["properties_json"])
            )
        return None

    def add_relationship(self, relationship: Relationship) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Resolve source and target names to their canonical node IDs checking names and aliases
            def find_entity_id(name: str) -> Optional[int]:
                cursor.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (name,))
                row = cursor.fetchone()
                if row:
                    return row[0]
                cursor.execute("SELECT id, aliases_json FROM entities")
                rows = cursor.fetchall()
                for r in rows:
                    aliases = json.loads(r["aliases_json"] or "[]")
                    if name.lower() in [a.lower() for a in aliases]:
                        return r["id"]
                return None

            src_id = find_entity_id(relationship.source_name)
            tgt_id = find_entity_id(relationship.target_name)

            if not src_id or not tgt_id:
                logger.warning(f"Could not build relationship. Source '{relationship.source_name}' (ID: {src_id}) or Target '{relationship.target_name}' (ID: {tgt_id}) not found.")
                return False

            cursor.execute(
                "INSERT OR IGNORE INTO relationships (source_entity_id, target_entity_id, relation_type) VALUES (?, ?, ?)",
                (src_id, tgt_id, relationship.relation_type.upper())
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to add relationship {relationship.source_name} -> {relationship.relation_type} -> {relationship.target_name}: {e}")
            return False
        finally:
            conn.close()

    def get_relationships(self, entity_name: str) -> List[Dict[str, Any]]:
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

    def get_multi_hop_relationships(self, entity_name: str, depth: int = 2) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
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

    def get_all_nodes(self) -> List[Entity]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities")
        rows = cursor.fetchall()
        conn.close()
        return [
            Entity(
                name=r["name"],
                entity_type=r["entity_type"],
                description=r["description"],
                aliases=json.loads(r["aliases_json"] or "[]"),
                properties=json.loads(r["properties_json"])
            ) for r in rows
        ]

    def get_all_relationships(self) -> List[Dict[str, Any]]:
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


class Neo4jGraphStore(BaseGraphStore):
    def __init__(self, uri: str, user: str = "neo4j", password: str = None):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_schema()

    def _ensure_schema(self):
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT UNIQUE_ENTITY_NAME IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")

    def add_node(self, entity: Entity) -> int:
        properties = entity.properties.copy()
        properties["description"] = entity.description or ""
        properties_json = json.dumps(properties)
        query = (
            "MERGE (e:Entity {name: $name}) "
            "ON CREATE SET e.entity_type = $entity_type, e.properties = $properties_json "
            "ON MATCH SET e.properties = apoc.map.merge(coalesce(e.properties, '{}'), $properties_json) "
            "RETURN id(e) AS id"
        )
        fallback_query = (
            "MERGE (e:Entity {name: $name}) "
            "ON CREATE SET e.entity_type = $entity_type, e.properties = $properties_json "
            "ON MATCH SET e.properties = $properties_json "
            "RETURN id(e) AS id"
        )
        with self.driver.session() as session:
            try:
                res = session.run(query, name=entity.name, entity_type=entity.entity_type, properties_json=properties_json)
                record = res.single()
                return record["id"]
            except Exception:
                res = session.run(fallback_query, name=entity.name, entity_type=entity.entity_type, properties_json=properties_json)
                record = res.single()
                return record["id"]

    def get_node(self, name: str) -> Optional[Entity]:
        query = "MATCH (e:Entity {name: $name}) RETURN id(e) AS id, e.entity_type AS entity_type, e.name AS name, e.properties AS properties"
        with self.driver.session() as session:
            res = session.run(query, name=name)
            record = res.single()
            if record:
                props = json.loads(record["properties"])
                description = props.pop("description", None)
                return Entity(
                    name=record["name"],
                    entity_type=record["entity_type"],
                    description=description,
                    properties=props
                )
        return None

    def add_relationship(self, relationship: Relationship) -> bool:
        relation_type = relationship.relation_type.upper().replace(" ", "_")
        query = (
            f"MATCH (a:Entity {{name: $source_name}}), (b:Entity {{name: $target_name}}) "
            f"MERGE (a)-[r:{relation_type}]->(b) "
            f"RETURN id(r) AS id"
        )
        with self.driver.session() as session:
            res = session.run(query, source_name=relationship.source_name, target_name=relationship.target_name)
            record = res.single()
            return record is not None

    def get_relationships(self, entity_name: str) -> List[Dict[str, Any]]:
        return self.get_multi_hop_relationships(entity_name, depth=1)

    def get_multi_hop_relationships(self, entity_name: str, depth: int = 2) -> List[Dict[str, Any]]:
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

    def get_all_nodes(self) -> List[Entity]:
        query = "MATCH (e:Entity) RETURN id(e) AS id, e.entity_type AS entity_type, e.name AS name, e.properties AS properties"
        with self.driver.session() as session:
            res = session.run(query)
            nodes = []
            for r in res:
                props = json.loads(r["properties"])
                description = props.pop("description", None)
                nodes.append(
                    Entity(
                        name=r["name"],
                        entity_type=r["entity_type"],
                        description=description,
                        properties=props
                    )
                )
            return nodes

    def get_all_relationships(self) -> List[Dict[str, Any]]:
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
