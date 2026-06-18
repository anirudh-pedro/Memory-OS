import sqlite3
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ProjectAggregator:
    def __init__(self, db_path: str = "memory.db"):
        self.db_path = db_path

    def get_project_summary(self) -> List[Dict[str, Any]]:
        """Aggregates all project details, including technologies, repos, docs, and recent activities."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # 1. Fetch all projects
            cursor.execute("SELECT id, name, description, properties_json FROM entities WHERE entity_type = 'Project'")
            project_rows = cursor.fetchall()
            
            projects_summary = []
            for row in project_rows:
                proj_id = row["id"]
                proj_name = row["name"]
                desc_val = row["description"] or "No description available."
                # Truncate description to keep context concise
                desc = desc_val[:150] + ("..." if len(desc_val) > 150 else "")
                props = json.loads(row["properties_json"] or "{}")
                
                # Find related technologies
                cursor.execute(
                    """
                    SELECT DISTINCT e.name FROM relationships r
                    JOIN entities e ON r.source_entity_id = e.id OR r.target_entity_id = e.id
                    WHERE (r.source_entity_id = ? OR r.target_entity_id = ?) AND e.entity_type = 'Technology' AND e.id != ?
                    """,
                    (proj_id, proj_id, proj_id)
                )
                techs = [r["name"] for r in cursor.fetchall()]
                
                # Find related repositories
                cursor.execute(
                    """
                    SELECT DISTINCT e.name FROM relationships r
                    JOIN entities e ON r.source_entity_id = e.id OR r.target_entity_id = e.id
                    WHERE (r.source_entity_id = ? OR r.target_entity_id = ?) AND e.entity_type = 'Repository' AND e.id != ?
                    """,
                    (proj_id, proj_id, proj_id)
                )
                repos = [r["name"] for r in cursor.fetchall()]
                
                # Find related documents
                cursor.execute(
                    """
                    SELECT DISTINCT e.name FROM relationships r
                    JOIN entities e ON r.source_entity_id = e.id OR r.target_entity_id = e.id
                    WHERE (r.source_entity_id = ? OR r.target_entity_id = ?) AND e.entity_type = 'Document' AND e.id != ?
                    """,
                    (proj_id, proj_id, proj_id)
                )
                docs = [r["name"] for r in cursor.fetchall()]
                
                # Fetch recent activities from workspace_cache that match project or repository names
                recent_activity = []
                query_terms = [proj_name] + repos
                for term in query_terms:
                    term_clean = term.split("/")[-1] if "/" in term else term
                    if len(term_clean) > 2:
                        cursor.execute(
                            """
                            SELECT source_app, title, last_synced FROM workspace_cache
                            WHERE title LIKE ? OR content LIKE ?
                            ORDER BY last_synced DESC LIMIT 3
                            """,
                            (f"%{term_clean}%", f"%{term_clean}%")
                        )
                        for r in cursor.fetchall():
                            activity_str = f"[{r['last_synced']}] [{r['source_app'].upper()}] {r['title']}"
                            if activity_str not in recent_activity:
                                recent_activity.append(activity_str)
                
                projects_summary.append({
                    "project_name": proj_name,
                    "description": desc,
                    "properties": props,
                    "technologies": list(set(techs)),
                    "repositories": list(set(repos)),
                    "documents": list(set(docs)),
                    "recent_activity": recent_activity[:3]  # limit to top 3 recent activities
                })
                
            return projects_summary
        except Exception as e:
            logger.error(f"Failed to aggregate project summaries: {e}")
            return []
        finally:
            conn.close()
