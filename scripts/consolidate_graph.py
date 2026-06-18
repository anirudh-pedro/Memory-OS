import sys
import os
import json
import logging
import sqlite3
from dotenv import load_dotenv

# Adjust Python path to load modules from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import DatabaseConnectionManager
from core.graph_store import SQLiteGraphStore
from core.models import Entity, Relationship
from memory.quality import EntityValidator, ProjectDetector, TechnologyClassifier, ProjectClassifier
from scripts.reindex_all import run_migration_and_reindex
from langchain_groq import ChatGroq

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("consolidate_graph")

def consolidate_graph():
    load_dotenv()
    db_path = "memory.db"
    db_manager = DatabaseConnectionManager(db_path=db_path)
    
    # Initialize LLM
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=os.getenv("GROQ_API_KEY")
    )
    project_classifier = ProjectClassifier(llm)

    neo4j_uri = os.getenv("NEO4J_URI")
    if neo4j_uri:
        logger.info("Neo4j graph store detected, skipping SQLite-specific consolidation.")

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    
    try:
        # --- 0. Pre-extract missing core entities/technologies from workspace cache ---
        logger.info("Step 0: Pre-extracting entities from workspace cache to seed technology nodes...")
        from core.extractor import GraphRAGExtractor
        extractor = GraphRAGExtractor(llm, SQLiteGraphStore(db_path))
        
        tech_keywords = ["React", "FastAPI", "MongoDB", "PostgreSQL", "Docker", "Kafka", "Neo4j", "Qdrant", "TypeScript", "LangGraph", "Python", "JavaScript", "Node.js"]
        
        like_clauses = " OR ".join(["content LIKE ?" for _ in tech_keywords] + ["title LIKE ?" for _ in tech_keywords])
        params = [f"%{k}%" for k in tech_keywords] + [f"%{k}%" for k in tech_keywords]
        
        cursor.execute(f"SELECT title, content FROM workspace_cache WHERE {like_clauses}", params)
        cache_rows = cursor.fetchall()
        
        def score_row(row):
            text = f"{row['title']} {row['content']}".lower()
            keyword_score = sum(1 for k in tech_keywords if k.lower() in text)
            length_score = min(len(text) / 1000.0, 1.0)
            return keyword_score + length_score
            
        sorted_rows = sorted(cache_rows, key=score_row, reverse=True)
        target_rows = sorted_rows[:15]
        
        logger.info(f"Found {len(cache_rows)} cache rows. Running GraphRAG extraction on top {len(target_rows)} rows...")
        import time
        extracted_count = 0
        for row in target_rows:
            content = f"Title: {row['title']}\nContent: {row['content']}"
            logger.info(f"Extracting from cache entry: '{row['title']}'")
            if extractor.extract_and_merge(content):
                extracted_count += 1
                time.sleep(2.0)
                
        logger.info(f"Completed Step 0: Extracted from {extracted_count} cache entries.")
        conn.commit()

        # --- 1. Noise, Placeholder, and Technology Classifier overrides ---
        logger.info("Step 1: Running basic validation and mapping Technology nodes...")
        cursor.execute("SELECT id, name, entity_type, description, aliases_json, properties_json FROM entities")
        all_nodes = cursor.fetchall()
        
        deleted_count = 0
        tech_mapped_count = 0
        
        for row in all_nodes:
            node_id = row["id"]
            name = row["name"]
            entity_type = row["entity_type"]
            desc = row["description"] or ""
            aliases = json.loads(row["aliases_json"] or "[]")
            properties = json.loads(row["properties_json"] or "{}")
            
            entity = Entity(
                name=name,
                entity_type=entity_type,
                description=desc,
                aliases=aliases,
                properties=properties
            )
            
            # Technology check
            tech_canonical = TechnologyClassifier.classify(name)
            if tech_canonical:
                # Check if it already exists in the database
                cursor.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (tech_canonical,))
                existing_tech = cursor.fetchone()
                
                if existing_tech:
                    existing_id = existing_tech[0]
                    if existing_id != node_id:
                        logger.info(f"Merging generic/project node '{name}' into existing Technology '{tech_canonical}'")
                        # Make sure the existing canonical node is set to type 'Technology'
                        cursor.execute("UPDATE entities SET entity_type = 'Technology' WHERE id = ?", (existing_id,))
                        # Re-map relationships
                        cursor.execute("UPDATE OR IGNORE relationships SET source_entity_id = ? WHERE source_entity_id = ?", (existing_id, node_id))
                        cursor.execute("UPDATE OR IGNORE relationships SET target_entity_id = ? WHERE target_entity_id = ?", (existing_id, node_id))
                        cursor.execute("DELETE FROM relationships WHERE source_entity_id = target_entity_id")
                        # Delete the duplicate node
                        cursor.execute("DELETE FROM entities WHERE id = ?", (node_id,))
                    else:
                        # It is the same node! Just update its entity type to Technology
                        cursor.execute("UPDATE entities SET entity_type = 'Technology' WHERE id = ?", (node_id,))
                else:
                    logger.info(f"Mapping generic/project node to canonical Technology: '{name}' -> '{tech_canonical}'")
                    cursor.execute(
                        "UPDATE entities SET entity_type = 'Technology', name = ? WHERE id = ?",
                        (tech_canonical, node_id)
                    )
                tech_mapped_count += 1
                continue

            # Standard validator checks
            if not EntityValidator.is_valid(entity):
                logger.info(f"Removing noise/placeholder node: '{name}' ({entity_type})")
                cursor.execute("DELETE FROM entities WHERE id = ?", (node_id,))
                deleted_count += 1
        
        logger.info(f"Completed Step 1: Removed {deleted_count} noise nodes, mapped {tech_mapped_count} technologies.")
        conn.commit()

        # --- 2. Batch Project Classification ---
        logger.info("Step 2: Classifying project candidate nodes in batches...")
        cursor.execute("SELECT id, name, description FROM entities WHERE entity_type = 'Project'")
        project_rows = cursor.fetchall()
        
        project_names = [row["name"] for row in project_rows]
        valid_projects = set(project_classifier.batch_classify_projects(project_names))
        
        # Add core predefined projects to avoid false negatives
        valid_projects.add("Memory-OS")
        valid_projects.add("DataCue")
        valid_projects.add("Bug Tracker")
        valid_projects.add("AgriChain")
        valid_projects.add("BlogSphere")
        
        purged_projects_count = 0
        for row in project_rows:
            node_id = row["id"]
            name = row["name"]
            if name not in valid_projects:
                logger.info(f"Purging generic word/invalid project node: '{name}'")
                cursor.execute("DELETE FROM entities WHERE id = ?", (node_id,))
                purged_projects_count += 1
                
        logger.info(f"Completed Step 2: Purged {purged_projects_count} invalid project nodes.")
        conn.commit()
        
        # --- 3. Repository Canonicalization & Duplicate Merging ---
        logger.info("Step 3: Performing repository canonicalization and duplicates merging...")
        # Re-fetch remaining nodes to get accurate current list
        cursor.execute("SELECT id, name, entity_type, description, aliases_json, properties_json FROM entities")
        remaining_nodes = cursor.fetchall()
        
        canonical_map = {}
        merged_count = 0
        
        for row in remaining_nodes:
            node_id = row["id"]
            name = row["name"]
            entity_type = row["entity_type"]
            description = row["description"] or ""
            aliases = json.loads(row["aliases_json"] or "[]")
            properties = json.loads(row["properties_json"] or "{}")
            
            # Repository lowercase & canonical check
            if entity_type == "Repository":
                name = name.strip().lower()
                aliases = [a.strip().lower() for a in aliases]
            
            # Check matches in processed canonical map
            matched_key = None
            for canon_name, val in canonical_map.items():
                canon_id, canon_ent = val
                if canon_ent.entity_type != entity_type:
                    continue
                
                # Check direct or alias match
                name_match = (canon_name.lower() == name.lower() or 
                              name.lower() in [a.lower() for a in canon_ent.aliases] or
                              canon_name.lower() in [a.lower() for a in aliases])
                
                # If repository, also support flat-vs-full path match
                if not name_match and entity_type == "Repository":
                    if "/" not in name and "/" in canon_name and canon_name.endswith(f"/{name}"):
                        name_match = True
                    elif "/" in name and "/" not in canon_name and name.endswith(f"/{canon_name}"):
                        name_match = True
                
                if name_match:
                    matched_key = canon_name
                    break
            
            if matched_key:
                # Merge into existing canonical node
                canon_id, canon_ent = canonical_map[matched_key]
                
                final_name = canon_ent.name
                if entity_type == "Repository":
                    final_name = final_name.lower()
                    if "/" in name and "/" not in canon_ent.name:
                        final_name = name.lower()
                        logger.info(f"Promoting canonical name to full repo path: '{final_name}' (old: '{canon_ent.name}')")
                
                canon_ent.properties.update(properties)
                if description and description not in canon_ent.description:
                    canon_ent.description = f"{canon_ent.description}\n{description}".strip()
                
                if name.lower() != final_name.lower() and name not in canon_ent.aliases:
                    canon_ent.aliases.append(name)
                for a in aliases:
                    if a.lower() != final_name.lower() and a not in canon_ent.aliases:
                        canon_ent.aliases.append(a)
                if canon_ent.name.lower() != final_name.lower() and canon_ent.name not in canon_ent.aliases:
                    canon_ent.aliases.append(canon_ent.name)
                    
                canon_ent.name = final_name
                
                cursor.execute(
                    "UPDATE entities SET name = ?, description = ?, aliases_json = ?, properties_json = ? WHERE id = ?",
                    (canon_ent.name, canon_ent.description, json.dumps(canon_ent.aliases), json.dumps(canon_ent.properties), canon_id)
                )
                
                # Re-map relationship rows
                cursor.execute("UPDATE OR IGNORE relationships SET source_entity_id = ? WHERE source_entity_id = ?", (canon_id, node_id))
                cursor.execute("UPDATE OR IGNORE relationships SET target_entity_id = ? WHERE target_entity_id = ?", (canon_id, node_id))
                cursor.execute("DELETE FROM relationships WHERE source_entity_id = target_entity_id")
                cursor.execute("DELETE FROM entities WHERE id = ?", (node_id,))
                
                canonical_map[final_name] = (canon_id, canon_ent)
                merged_count += 1
                logger.info(f"Merged duplicate node '{name}' into canonical '{final_name}'")
            else:
                aliases_to_save = aliases.copy()
                if name not in aliases_to_save:
                    aliases_to_save.append(name)
                new_ent = Entity(
                    name=name,
                    entity_type=entity_type,
                    description=description,
                    aliases=aliases_to_save,
                    properties=properties
                )
                canonical_map[name] = (node_id, new_ent)
                
        logger.info(f"Completed Step 3: Merged {merged_count} duplicate entities.")
        conn.commit()

        # --- 4. Rebuild Project Relationships & Auto-Linking ---
        logger.info("Step 4: Running project detector and establishing relationships...")
        graph_store = SQLiteGraphStore(db_path)
        detector = ProjectDetector(db_manager, graph_store)
        detector.run_detection()
        
    except sqlite3.Error as e:
        logger.error(f"SQLite transaction failed during consolidation: {e}")
        conn.rollback()
        raise e
    finally:
        conn.close()
        
    # --- 5. Rebuild Vector Index ---
    logger.info("Step 5: Rebuilding vector DB indexing...")
    run_migration_and_reindex()
    logger.info("Consolidation job completed successfully!")

if __name__ == "__main__":
    consolidate_graph()
