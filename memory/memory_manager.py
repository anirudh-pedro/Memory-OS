import sqlite3
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MessageRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()

    def save_message(self, thread_id: str, role: str, content: str, metadata: dict = None) -> int:
        metadata = metadata or {}
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO messages (thread_id, role, content, metadata_json) VALUES (?, ?, ?, ?)",
                (thread_id, role, content, json.dumps(metadata))
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Failed to save message: {e}")
            raise e
        finally:
            conn.close()

    def get_messages(self, thread_id: str) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at ASC", (thread_id,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "thread_id": r["thread_id"],
                "role": r["role"],
                "content": r["content"],
                "metadata": json.loads(r["metadata_json"]),
                "created_at": r["created_at"]
            } for r in rows
        ]

    def clear_thread(self, thread_id: str) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()


class WorkspaceCacheRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_app TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}',
                last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_app, external_id)
            )
            """
        )
        conn.commit()
        conn.close()

    def upsert_cache(self, source_app: str, external_id: str, title: str, content: str = "", metadata: dict = None) -> bool:
        metadata = metadata or {}
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO workspace_cache (source_app, external_id, title, content, metadata_json, last_synced)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_app, external_id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    last_synced = excluded.last_synced
                """,
                (source_app, external_id, title, content, json.dumps(metadata), datetime.now().isoformat())
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to upsert workspace cache: {e}")
            return False
        finally:
            conn.close()

    def get_cache(self, source_app: str, external_id: str) -> dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM workspace_cache WHERE source_app = ? AND external_id = ?", (source_app, external_id))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "id": row["id"],
                "source_app": row["source_app"],
                "external_id": row["external_id"],
                "title": row["title"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"]),
                "last_synced": row["last_synced"]
            }
        return None

    def get_all_cached_items(self, source_app: str = None) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        if source_app:
            cursor.execute("SELECT * FROM workspace_cache WHERE source_app = ? ORDER BY last_synced DESC", (source_app,))
        else:
            cursor.execute("SELECT * FROM workspace_cache ORDER BY last_synced DESC")
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "source_app": r["source_app"],
                "external_id": r["external_id"],
                "title": r["title"],
                "content": r["content"],
                "metadata": json.loads(r["metadata_json"]),
                "last_synced": r["last_synced"]
            } for r in rows
        ]

    def clear_cache(self, source_app: str = None) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        if source_app:
            cursor.execute("DELETE FROM workspace_cache WHERE source_app = ?", (source_app,))
        else:
            cursor.execute("DELETE FROM workspace_cache")
        conn.commit()
        conn.close()
