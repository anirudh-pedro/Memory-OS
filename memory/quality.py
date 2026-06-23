import json
import logging
import re
import sqlite3
from typing import List, Dict, Any, Optional
from core.models import Entity, Relationship
from core.graph_store import BaseGraphStore
from core.db import DatabaseConnectionManager
from pydantic import BaseModel, Field
from ontology.entity_types import EntityType
from ontology.relationship_types import RelationshipType

logger = logging.getLogger(__name__)

class TechnologyClassifier:
    TECH_MAP = {
        "python": "Python",
        "javascript": "JavaScript",
        "js": "JavaScript",
        "typescript": "TypeScript",
        "ts": "TypeScript",
        "node.js": "Node.js",
        "nodejs": "Node.js",
        "node": "Node.js",
        "react": "React",
        "reactjs": "React",
        "mongodb": "MongoDB",
        "mongo": "MongoDB",
        "postgresql": "PostgreSQL",
        "postgres": "PostgreSQL",
        "docker": "Docker",
        "kafka": "Kafka",
        "neo4j": "Neo4j",
        "qdrant": "Qdrant",
        "fastapi": "FastAPI",
        "langgraph": "LangGraph",
        "go": "Go",
        "golang": "Go",
        "php": "PHP",
        "flask": "Flask",
        "laravel": "Laravel",
        "symfony": "Symfony",
        "chromadb": "ChromaDB",
        "firebase": "Firebase",
        "sqlite": "SQLite",
        "mysql": "MySQL",
        "streamlit": "Streamlit",
        "vercel": "Vercel"
    }

    @classmethod
    def classify(cls, name: str) -> Optional[str]:
        """Recognizes technology names and returns the canonical technology name, or None."""
        name_clean = name.strip().lower().replace("-", "").replace(" ", "")
        
        # 1. Exact match
        if name_clean in cls.TECH_MAP:
            return cls.TECH_MAP[name_clean]
        
        # 2. Substring match
        for k, canonical in cls.TECH_MAP.items():
            if len(k) > 2 and k in name_clean:
                return canonical
        return None


class ProjectClassification(BaseModel):
    is_project: bool = Field(description="True if the entity represents a specific software project, application, tool, or spec document.")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0.")
    reasoning: str = Field(description="Explanation of classification decision.")


class BatchProjectClassification(BaseModel):
    valid_projects: List[str] = Field(description="List of names that are confirmed to be valid specific software/document projects.")


class ProjectClassifier:
    def __init__(self, llm=None):
        self.llm = llm
        self.structured_llm = None
        self.batch_structured_llm = None
        if self.llm:
            try:
                self.structured_llm = self.llm.with_structured_output(ProjectClassification)
                self.batch_structured_llm = self.llm.with_structured_output(BatchProjectClassification)
            except Exception as e:
                logger.warning(f"Could not init structured output for ProjectClassifier: {e}")

    def is_valid_project(self, name: str, description: str = "", source: str = "") -> bool:
        """Determines if a candidate Project name is a valid project."""
        name_lower = name.strip().lower()

        # Check explicit generic noise terms
        if name_lower in {
            "missing", "setup", "start", "count", "good", "element", "matrix", "main", "process", 
            "processing", "value", "using", "built", "made", "this", "each", "whether", "ensure",
            "count", "install", "check", "ensure", "largest", "option", "account", "target", "configure",
            "insert", "single", "search", "role", "navigate", "usage", "greater", "closest", "design",
            "graph", "error", "data", "alternating", "only", "maximum", "score", "that", "type", "document",
            "medium", "language", "characters", "between", "common", "stack", "elements", "points",
            "query", "duplicate", "shortest", "reverse", "pairs", "timezone", "water", "longest",
            "validate", "interval", "lists", "substring", "problem", "access", "arrays", "word", "strings",
            "subarray", "minimize", "schedule", "right", "update", "advanced", "difference", "clone",
            "simple", "change", "valid", "delete", "last", "sorted", "subsequence", "description",
            "number", "game", "increasing", "house", "numbers", "rotated", "dictionary", "square",
            "unique", "combination", "deploy", "window", "length", "view", "rotate", "size", "palindrome",
            "automatic", "edit", "nodes", "find", "minimum", "best", "given", "open", "zero", "trees",
            "equal", "remove", "duplicates", "system", "dynamic", "cache", "first", "intervals", "default",
            "operations", "time", "next", "string", "server", "quick", "auth", "node", "make", "missing",
            "function", "main", "process", "jump", "subsets", "your", "element", "range", "stock",
            "environment", "setup", "traversal", "position", "matrix"
        }:
            return False

        # If name matches a technology, it is NOT a project
        if TechnologyClassifier.classify(name) is not None:
            return False

        # Git repositories or Notion projects
        if source in ["github", "notion"] or "repository" in name.lower() or "/" in name:
            if len(name_lower) <= 2:
                return False
            return True

        if not self.structured_llm:
            return len(name_lower) > 3

        # Use LLM with confidence >= 0.8
        try:
            prompt = (
                f"You are an expert ontology classifier.\n"
                f"Determine if the entity '{name}' represents a specific software project, application, tool, library, spec document, or database project (e.g. Memory-OS, AgriChain, PageForge, DataCue).\n\n"
                f"Entity Name: {name}\n"
                f"Description/Context: {description}\n"
                f"Source: {source}\n\n"
                f"Rules:\n"
                f"- Specific software systems, apps, repositories, or spec documents are Projects.\n"
                f"- Generic words, adjectives, verbs, programming keywords, tasks, or coding puzzles (e.g. Missing, Setup, Main, Alternating, Reverse, Rotated, Jump) are NOT Projects.\n"
                f"- Technologies (e.g. React, Python) are NOT Projects."
            )
            res = self.structured_llm.invoke(prompt)
            return res.is_project and res.confidence >= 0.8
        except Exception as e:
            logger.warning(f"Project classification failed: {e}")
            return len(name_lower) > 3

    def batch_classify_projects(self, names: List[str]) -> List[str]:
        """Classifies a list of project names in batches to optimize LLM usage and avoid rate limits."""
        if not self.batch_structured_llm:
            return [n for n in names if self.is_valid_project(n)]

        valid_results = []
        batch_size = 40
        for i in range(0, len(names), batch_size):
            batch = names[i:i+batch_size]
            
            # Simple pre-filter for obvious noise
            filtered_batch = []
            for n in batch:
                n_lower = n.strip().lower()
                # If it's an obvious technology or generic term, skip
                if n_lower in {
                    "missing", "setup", "start", "count", "good", "element", "matrix", "main", "process", 
                    "processing", "value", "using", "built", "made", "this", "each", "whether", "ensure",
                    "count", "install", "check", "ensure", "largest", "option", "account", "target", "configure",
                    "insert", "single", "search", "role", "navigate", "usage", "greater", "closest", "design",
                    "graph", "error", "data", "alternating", "only", "maximum", "score", "that", "type", "document",
                    "medium", "language", "characters", "between", "common", "stack", "elements", "points",
                    "query", "duplicate", "shortest", "reverse", "pairs", "timezone", "water", "longest",
                    "validate", "interval", "lists", "substring", "problem", "access", "arrays", "word", "strings",
                    "subarray", "minimize", "schedule", "right", "update", "advanced", "difference", "clone",
                    "simple", "change", "valid", "delete", "last", "sorted", "subsequence", "description",
                    "number", "game", "increasing", "house", "numbers", "rotated", "dictionary", "square",
                    "unique", "combination", "deploy", "window", "length", "view", "rotate", "size", "palindrome",
                    "automatic", "edit", "nodes", "find", "minimum", "best", "given", "open", "zero", "trees",
                    "equal", "remove", "duplicates", "system", "dynamic", "cache", "first", "intervals", "default",
                    "operations", "time", "next", "string", "server", "quick", "auth", "node", "make", "missing",
                    "function", "main", "process", "jump", "subsets", "your", "element", "range", "stock",
                    "environment", "setup", "traversal", "position", "matrix"
                }:
                    continue
                if TechnologyClassifier.classify(n) is not None:
                    continue
                filtered_batch.append(n)

            if not filtered_batch:
                continue

            try:
                prompt = (
                    "You are an expert ontology classifier. From the list of candidate entity names, select only the ones that "
                    "are valid, specific software projects, applications, tools, spec documents, or database projects (e.g. Memory-OS, AgriChain, PageForge, DataCue).\n\n"
                    "Reject generic words, programming keywords, technologies (like React, Python, FastAPI), actions, or common adjectives/verbs (e.g. Missing, Setup, Main, Cost, Single, Stock, Traversals, Subsets, Start, Count, Good, Element, Setup, Matrix).\n\n"
                    "CRITICAL: You MUST call the tool and return the `valid_projects` list (which may be empty `[]` if none of the candidate names are valid projects). Never reply with plain text.\n\n"
                    f"Candidate Names:\n{json.dumps(filtered_batch)}"
                )
                res = self.batch_structured_llm.invoke(prompt)
                valid_results.extend(res.valid_projects)
            except Exception as e:
                logger.warning(f"Batch project classification failed: {e}")
                # Fallback to individual checks
                for name in filtered_batch:
                    if self.is_valid_project(name):
                        valid_results.append(name)
        return valid_results


class EntityValidator:
    @staticmethod
    def is_valid(entity: Entity) -> bool:
        """Filter out placeholders, noise nodes, generic conversational instructions, and dummy defaults."""
        entity.name = re.sub(r'[\u2010-\u2015\u2043]', '-', entity.name.strip())
        name = entity.name.strip()
        if not name:
            return False
            
        # Reject single character or numeric values
        if len(name) <= 1 or name.isnumeric():
            return False
            
        name_lower = name.lower()
        
        # 1.5. Reject blacklisted conversational entities
        BLACKLISTED_ENTITIES = {
            "assistant", "user", "response", "query", "me", "you", "system", "ai", "model", 
            "agent", "bot", "messages", "chat", "history", "message", "conversation", "greeting",
            "llm", "prompt", "context", "metadata", "properties", "result", "thanks", "hello", "hi"
        }
        if name_lower in BLACKLISTED_ENTITIES:
            return False
        
        # 1. Reject bracket placeholders (<unknown_repository>, <owner>/<repo>)
        if name.startswith("<") or name.endswith(">"):
            return False
            
        # 2. Reject general placeholders
        placeholders = {
            "unknown", "null", "none", "test", "untitled", "placeholder", 
            "generic response", "unknown_repository", "owner/repo", "undefined",
            "self email", "expected email", "workshop follow-up", "create notion page",
            "create something new", "send email with workshop details", "github repository/issue",
            "good first issue"
        }
        if name_lower in placeholders:
            return False
            
        # 3. Reject generic prompt elements or action verbs
        invalid_prefixes = (
            "create ", "run ", "add ", "fetch ", "expected ", 
            "join ", "prepare ", "search ", "send ", "write ", 
            "register ", "list ", "configure ", "install ", "set up ",
            "email ", "emails "
        )
        if any(name_lower.startswith(prefix) for prefix in invalid_prefixes):
            return False
            
        if name_lower == "email" or name_lower == "emails" or re.match(r"^email\s*\d+", name_lower):
            return False
            
        # 4. Reject long generic sentences
        if len(name_lower) > 40 and " " in name_lower:
            return False
            
        return True


class EntityResolver:
    def __init__(self, db_manager: DatabaseConnectionManager, graph_store: BaseGraphStore):
        self.db_manager = db_manager
        self.graph_store = graph_store

    def resolve_and_merge(self, entity: Entity) -> int:
        """Resolves duplicate entities, canonicalizes names, and updates aliases."""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            # Overrides for technology / repository format
            tech_canonical = TechnologyClassifier.classify(entity.name)
            if tech_canonical:
                entity.entity_type = EntityType.TECHNOLOGY
                entity.name = tech_canonical

            if entity.entity_type == EntityType.REPOSITORY:
                entity.name = entity.name.strip().lower()
                entity.aliases = [a.strip().lower() for a in entity.aliases]

            # Match existing entities across all types to enforce one canonical type
            cursor.execute("SELECT id, name, entity_type, description, aliases_json, properties_json FROM entities")
            rows = cursor.fetchall()
            
            matched_row = None
            for row in rows:
                row_name = row['name']
                row_aliases = json.loads(row['aliases_json'] or "[]")
                # Direct name check (case-insensitive)
                if row_name.lower() == entity.name.lower():
                    matched_row = row
                    break
                # Alias check (case-insensitive)
                if entity.name.lower() in [a.lower() for a in row_aliases]:
                    matched_row = row
                    break

            # If Repository check is needed
            if not matched_row:
                repo_rows = [r for r in rows if r['entity_type'] == "Repository"]
                if entity.entity_type == EntityType.REPOSITORY:
                    if "/" not in entity.name:
                        for row in repo_rows:
                            row_name = row['name']
                            if "/" in row_name and row_name.lower().endswith(f"/{entity.name.lower()}"):
                                matched_row = row
                                break
                    else:
                        flat_name = entity.name.split("/")[-1]
                        for row in repo_rows:
                            row_name = row['name']
                            if "/" not in row_name and row_name.lower() == flat_name.lower():
                                matched_row = row
                                break
            
            if matched_row:
                node_id = matched_row['id']
                existing_name = matched_row['name']
                entity.entity_type = matched_row['entity_type']  # Enforce canonical type!
                existing_aliases = json.loads(matched_row['aliases_json'] or "[]")
                existing_props = json.loads(matched_row['properties_json'] or "{}")
                
                # Merge properties
                existing_props.update(entity.properties)
                
                # Merge descriptions
                new_desc = matched_row['description'] or ""
                if entity.description and entity.description not in new_desc:
                    new_desc = f"{new_desc}\n{entity.description}".strip()
                
                # Canonical name resolution:
                final_name = existing_name
                if entity.entity_type == EntityType.REPOSITORY:
                    # Force lowercase format
                    final_name = final_name.lower()
                    if "/" in entity.name and "/" not in existing_name:
                        final_name = entity.name.lower()
                        if existing_name not in existing_aliases:
                            existing_aliases.append(existing_name)
                        logger.info(f"Promoted canonical repository name to: '{final_name}' (old: '{existing_name}')")
                
                # Add aliases
                if entity.name.lower() != final_name.lower() and entity.name not in existing_aliases:
                    existing_aliases.append(entity.name)
                for a in entity.aliases:
                    if a.lower() != final_name.lower() and a not in existing_aliases:
                        existing_aliases.append(a)

                cursor.execute(
                    "UPDATE entities SET name = ?, description = ?, aliases_json = ?, properties_json = ? WHERE id = ?",
                    (final_name, new_desc, json.dumps(existing_aliases), json.dumps(existing_props), node_id)
                )
                
                # Update any relationships linking to the old name to match the final name
                if final_name.lower() != existing_name.lower():
                    self._update_relationship_references(existing_name, final_name, cursor)
                
                logger.info(f"Resolved and merged duplicate entity '{entity.name}' into canonical: '{final_name}'")
                conn.commit()
                return node_id
            else:
                # Insert new node
                aliases_to_save = entity.aliases.copy()
                if entity.name not in aliases_to_save:
                    aliases_to_save.append(entity.name)
                cursor.execute(
                    "INSERT INTO entities (entity_type, name, description, aliases_json, properties_json) VALUES (?, ?, ?, ?, ?)",
                    (entity.entity_type, entity.name, entity.description, json.dumps(aliases_to_save), json.dumps(entity.properties))
                )
                node_id = cursor.lastrowid
                conn.commit()
                return node_id
        except sqlite3.Error as e:
            logger.error(f"Failed to merge entity node: {e}")
            raise e
        finally:
            conn.close()

    def _update_relationship_references(self, old_name: str, new_name: str, cursor: sqlite3.Cursor):
        """Update any relationships that linked to the old entity name to use the new canonical name."""
        try:
            # Retrieve entity IDs
            cursor.execute("SELECT id FROM entities WHERE name = ?", (new_name,))
            new_row = cursor.fetchone()
            if not new_row:
                return
            new_id = new_row[0]
            
            cursor.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (old_name,))
            old_row = cursor.fetchone()
            if not old_row:
                return
            old_id = old_row[0]
            
            # Update source references
            cursor.execute(
                "UPDATE OR IGNORE relationships SET source_entity_id = ? WHERE source_entity_id = ?",
                (new_id, old_id)
            )
            # Update target references
            cursor.execute(
                "UPDATE OR IGNORE relationships SET target_entity_id = ? WHERE target_entity_id = ?",
                (new_id, old_id)
            )
            # Delete redundant old references
            cursor.execute("DELETE FROM relationships WHERE source_entity_id = ? AND target_entity_id = ? AND source_entity_id = target_entity_id", (old_id, old_id))
        except sqlite3.Error as e:
            logger.warning(f"Could not update relationship links during node merge: {e}")


class ProjectDetector:
    def __init__(self, db_manager: DatabaseConnectionManager, graph_store: BaseGraphStore):
        self.db_manager = db_manager
        self.graph_store = graph_store

    def run_detection(self) -> List[str]:
        """Establish relationships for existing projects without creating frequency-based ones."""
        logger.info("Running project detector auto-linking...")
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT name FROM entities WHERE entity_type = 'Project'")
            projects = [row["name"] for row in cursor.fetchall()]
            
            for proj_name in projects:
                # Establish PART_OF/RELATED_TO links for existing projects
                cursor.execute("SELECT name, id, entity_type FROM entities WHERE LOWER(name) != LOWER(?)", (proj_name,))
                entities = cursor.fetchall()
                for ent in entities:
                    ent_name = ent["name"]
                    ent_type = ent["entity_type"]
                    if proj_name.lower() in ent_name.lower():
                        rel_type = "PART_OF" if ent_type in ["Repository", "Document", "Task"] else "RELATED_TO"
                        self.graph_store.add_relationship(
                            Relationship(
                                source_name=ent_name,
                                target_name=proj_name,
                                relation_type=rel_type
                            )
                        )
            return []
        except sqlite3.Error as e:
            logger.error(f"Project detection database failure: {e}")
            return []
        finally:
            conn.close()


class MemoryQualityPipeline:
    def __init__(self, db_manager: DatabaseConnectionManager, graph_store: BaseGraphStore, llm=None):
        self.db_manager = db_manager
        self.graph_store = graph_store
        self.llm = llm
        self.resolver = EntityResolver(db_manager, graph_store)
        self.project_detector = ProjectDetector(db_manager, graph_store)
        self.project_classifier = ProjectClassifier(llm)

    def process_entity(self, entity: Entity, source: str = "") -> Optional[int]:
        """Validate and resolve/merge entity node. Returns ID or -1 if rejected."""
        # 1. Technology check
        tech_canonical = TechnologyClassifier.classify(entity.name)
        if tech_canonical:
            entity.entity_type = EntityType.TECHNOLOGY
            entity.name = tech_canonical

        # 2. Project check
        if entity.entity_type == EntityType.PROJECT:
            if not self.project_classifier.is_valid_project(entity.name, entity.description or "", source):
                logger.info(f"Discarding invalid project entity: '{entity.name}'")
                return -1

        if not EntityValidator.is_valid(entity):
            logger.info(f"Discarding invalid/conversational entity: '{entity.name}' ({entity.entity_type})")
            return -1
        return self.resolver.resolve_and_merge(entity)

    def run_cache_consolidation(self) -> int:
        """Deduplicate workspace_cache rows with identical titles."""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        merged_count = 0
        try:
            cursor.execute("SELECT title, COUNT(*) as count FROM workspace_cache GROUP BY title HAVING count > 1")
            dup_rows = cursor.fetchall()
            for row in dup_rows:
                title = row["title"]
                cursor.execute(
                    "SELECT id, source_app, content, metadata_json, last_synced FROM workspace_cache WHERE title = ? ORDER BY last_synced ASC",
                    (title,)
                )
                items = cursor.fetchall()
                if len(items) <= 1:
                    continue
                
                primary_id = items[0]["id"]
                merged_content = items[0]["content"] or ""
                primary_metadata = json.loads(items[0]["metadata_json"] or "{}")
                primary_metadata["merged_sources"] = []
                
                for other in items[1:]:
                    other_content = other["content"] or ""
                    if other_content not in merged_content:
                        merged_content += f"\n\n--- Merged update from {other['last_synced']} ---\n" + other_content
                    other_meta = json.loads(other["metadata_json"] or "{}")
                    primary_metadata["merged_sources"].append(other_meta)
                    cursor.execute("DELETE FROM workspace_cache WHERE id = ?", (other["id"],))
                    merged_count += 1
                
                cursor.execute(
                    "UPDATE workspace_cache SET content = ?, metadata_json = ? WHERE id = ?",
                    (merged_content, json.dumps(primary_metadata), primary_id)
                )
            conn.commit()
            logger.info(f"Consolidated {merged_count} duplicate cache items.")
            return merged_count
        except sqlite3.Error as e:
            logger.error(f"Failed cache consolidation: {e}")
            return 0
        finally:
            conn.close()

    def run_full_consolidation(self):
        """Run all memory consolidations, cache merges, and project auto-detections."""
        self.run_cache_consolidation()
        self.project_detector.run_detection()
