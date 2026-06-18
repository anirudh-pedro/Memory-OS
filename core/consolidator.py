import sqlite3
import json
import logging
import re
from typing import List, Dict, Any
from core.db import DatabaseConnectionManager
from core.graph_store import BaseGraphStore
from core.models import Entity, Relationship

logger = logging.getLogger(__name__)

class MemoryConsolidator:
    def __init__(self, db_manager: DatabaseConnectionManager, graph_store: BaseGraphStore):
        self.db_manager = db_manager
        self.graph_store = graph_store

    def consolidate_cache(self) -> int:
        """Finds and merges duplicate workspace_cache entries with identical titles."""
        logger.info("Running workspace cache consolidation...")
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. Fetch duplicate titles
            cursor.execute(
                """
                SELECT title, COUNT(*) as count 
                FROM workspace_cache 
                GROUP BY title 
                HAVING count > 1
                """
            )
            dup_rows = cursor.fetchall()
            merged_count = 0
            
            for row in dup_rows:
                title = row["title"]
                cursor.execute(
                    "SELECT id, source_app, content, metadata_json, last_synced FROM workspace_cache WHERE title = ? ORDER BY last_synced ASC",
                    (title,)
                )
                items = cursor.fetchall()
                if len(items) <= 1:
                    continue
                
                # Keep the first item and append the content of others
                primary_id = items[0]["id"]
                merged_content = items[0]["content"] or ""
                
                # Merge metadata lists/dicts
                primary_metadata = json.loads(items[0]["metadata_json"] or "{}")
                primary_metadata["merged_sources"] = []
                
                for other in items[1:]:
                    other_content = other["content"] or ""
                    if other_content not in merged_content:
                        merged_content += f"\n\n--- Merged update from {other['last_synced']} ---\n" + other_content
                    
                    other_meta = json.loads(other["metadata_json"] or "{}")
                    primary_metadata["merged_sources"].append(other_meta)
                    
                    # Delete duplicate row
                    cursor.execute("DELETE FROM workspace_cache WHERE id = ?", (other["id"],))
                    merged_count += 1
                
                # Update primary row
                cursor.execute(
                    "UPDATE workspace_cache SET content = ?, metadata_json = ? WHERE id = ?",
                    (merged_content, json.dumps(primary_metadata), primary_id)
                )
            
            conn.commit()
            logger.info(f"Workspace cache consolidated: Merged and removed {merged_count} duplicate records.")
            return merged_count
        except sqlite3.Error as e:
            logger.error(f"Failed to consolidate cache: {e}")
            return 0
        finally:
            conn.close()

    def run_project_detection(self) -> List[str]:
        """Establish relationships for existing projects without creating frequency-based ones."""
        logger.info("Running automatic project linking...")
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
            
    def consolidate_all(self):
        """Executes all consolidation and project-creation algorithms."""
        self.consolidate_cache()
        self.run_project_detection()
