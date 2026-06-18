import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

class DatabaseConnectionManager:
    def __init__(self, db_path: str = "memory.db", schema_path: str = "database/schema.sql"):
        self.db_path = db_path
        self.schema_path = schema_path
        self.initialize_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize_db(self):
        """Ensures the SQLite database is created and initialized with schema and run migration checks."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 1. Run migrations / checks on existing database tables first
        try:
            # Check if entities table exists and if it has the description column
            cursor.execute("PRAGMA table_info(entities);")
            columns = cursor.fetchall()
            if columns:
                col_names = [col[1] for col in columns]
                if "description" not in col_names:
                    logger.info("Migrating entities table to add 'description' column...")
                    cursor.execute("ALTER TABLE entities ADD COLUMN description TEXT;")
                    conn.commit()
                    logger.info("Migrating entities table complete.")
                if "aliases_json" not in col_names:
                    logger.info("Migrating entities table to add 'aliases_json' column...")
                    cursor.execute("ALTER TABLE entities ADD COLUMN aliases_json TEXT DEFAULT '[]';")
                    conn.commit()
                    logger.info("Migrating entities table aliases_json complete.")
        except sqlite3.Error as e:
            logger.warning(f"Pre-migration check failed: {e}")

        # 2. Execute schema script to ensure tables/triggers exist
        if os.path.exists(self.schema_path):
            try:
                with open(self.schema_path, "r", encoding="utf-8") as f:
                    schema_script = f.read()
                cursor.executescript(schema_script)
                conn.commit()
                logger.info("Database schema validated and initialized successfully.")
            except sqlite3.Error as e:
                logger.error(f"Failed to execute schema script: {e}")
                raise e
        else:
            logger.warning(f"Schema file not found at {self.schema_path}. Skipping executing schema script.")

        conn.close()
