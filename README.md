# Memory-OS 🧠

Memory-OS is a CLI-based **Personal Knowledge Operating System (PKOS)**. It syncs your personal knowledge from external platforms — **GitHub**, **Gmail**, **Notion**, and **Google Calendar** — into a searchable second brain backed by **SQLite**, **Qdrant**, and **Neo4j**.

---

## ✨ Features

- **🔄 Multi-Source Sync**: Pulls data from GitHub (repos, issues, PRs, READMEs), Gmail (emails), Notion (pages), and Google Calendar (events) via Composio connectors.
- **🧠 Knowledge Graph**: Automatically extracts entities (People, Projects, Technologies, Tasks, etc.) and relationships using LLM-powered GraphRAG extraction, validated through a quality pipeline.
- **🔍 Hybrid Search**: Queries combine vector similarity (Qdrant TF-IDF), full-text search (SQLite FTS5), and graph neighbor traversal — fused into unified context for LLM-powered answers.
- **📊 Stats & Metrics**: View knowledge graph sizes, vector counts, entity breakdowns, and last sync timestamps.
- **🗑️ Date-Based Pruning**: Delete old records across all three stores with a single command.
- **💬 Natural Language Queries**: Ask questions about your synced knowledge and get direct answers powered by Groq LLMs.

---

## 🛠️ CLI Commands

| Command | Action |
| :--- | :--- |
| `sync` | Sync all connectors and ingest into SQLite, Qdrant, and Neo4j. |
| `sync --rebuild` | Full rebuild: refit embedder and recreate vector index. |
| `stats` | Display knowledge graph metrics, vector counts, and last sync time. |
| `delete --before YYYY-MM-DD` | Prune records older than the specified date. |
| `<natural language query>` | Ask a question — Memory-OS answers using hybrid RAG retrieval. |
| `exit` / `quit` | Exit the shell. |

---

## 📚 Documentation

The complete documentation for Memory-OS is located in the [`docs/`](docs/) directory.

*   **[Architecture & Design](docs/architecture/overview.md)**
*   **[Core Features](docs/features/core-features.md)**
*   **[CLI Usage](docs/cli/usage.md)**
*   **[Development Guide](docs/development/conventions.md)**

For a high-level overview of the codebase and technical debt audit, see the [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md).

---

## 🚀 Getting Started

### 1. Install Dependencies
```bash
uv sync
```

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
COMPOSIO_API_KEY=your_composio_api_key
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile

# Optional: Neo4j (falls back to SQLite graph store if not set)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

### 3. Run Memory-OS
```bash
uv run main.py
```

On first run, the CLI will guide you through OAuth flows to connect your GitHub, Gmail, Notion, and Google Calendar accounts.

