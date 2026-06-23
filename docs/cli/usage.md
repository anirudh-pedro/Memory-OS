# CLI Usage

Memory-OS is an interactive, shell-like terminal application. Run it using:

```bash
uv run main.py
```

## Available Commands

Once the prompt `[default_session] You:` appears, you can type the following commands:

### `sync`
Runs the ingestion pipeline for all configured connectors (GitHub, Gmail, Notion, Calendar). New or updated items are cached, embedded, run through GraphRAG extraction, and saved to the databases.

### `sync --rebuild`
Performs a full sync, but additionally refits the local TF-IDF embedder model on the entirety of the database corpus before updating the vector index.

### `stats`
Displays detailed metrics about the current state of your Personal Knowledge OS:
*   Last Synchronization time
*   Total Cached Documents
*   Total Logged Events
*   Entity counts by type
*   Total Relationships
*   Vector counts in Qdrant

### `delete --before YYYY-MM-DD`
Prunes the database by removing records older than the specified date. This operation spans the SQLite cache, the Qdrant vector store, and the Graph database.

### Natural Language Queries
Any input that is not recognized as a command is treated as a natural language query. Memory-OS will perform a hybrid search to gather context and stream back an LLM-generated response.

Example:
```text
[default_session] You: What technologies does the Memory-OS project use?
Thinking...

Memory-OS:
Based on your synced knowledge, Memory-OS uses Python, SQLite, Qdrant, Neo4j, LangChain, and Composio.
```

### `exit` / `quit`
Safely closes database connections and exits the application.
