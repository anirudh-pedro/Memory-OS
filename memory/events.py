import sqlite3
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class EventType:
    PROJECT_CREATED = "PROJECT_CREATED"
    PROJECT_UPDATED = "PROJECT_UPDATED"
    PROJECT_RENAMED = "PROJECT_RENAMED"
    TECH_ADDED = "TECH_ADDED"
    TASK_CREATED = "TASK_CREATED"
    TASK_COMPLETED = "TASK_COMPLETED"
    REPOSITORY_CREATED = "REPOSITORY_CREATED"
    MEMORY_INGESTED = "MEMORY_INGESTED"

class EventStore:
    def __init__(self, db_path: str = "metadata.db"):
        self.db_path = db_path

    def log_event(self, event_type: str, entity_name: str, payload: dict) -> int:
        """Logs a state change event to the events table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO events (event_type, entity_name, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (event_type, entity_name, json.dumps(payload), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            last_id = cursor.lastrowid
            logger.info(f"Logged event {event_type} for '{entity_name}' (ID: {last_id})")
            conn.close()
            return last_id
        except Exception as e:
            logger.error(f"Failed to log event: {e}")
            return -1

    def get_events(self, start_date: str = None, end_date: str = None) -> list:
        """Retrieves events within a date range."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT id, event_type, entity_name, payload_json, created_at FROM events WHERE 1=1"
            params = []
            if start_date:
                query += " AND created_at >= ?"
                params.append(start_date)
            if end_date:
                query += " AND created_at <= ?"
                params.append(f"{end_date} 23:59:59")
            query += " ORDER BY created_at ASC"
            cursor.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Failed to fetch events: {e}")
            return []
