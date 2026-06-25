# Memory‑OS

![banner](https://raw.githubusercontent.com/anirudh-pedro/Memory-OS/main/docs/banner.png)

**Memory‑OS** is a personal‑knowledge operating system that lets you **sync, index, and semantically search** across your GitHub repositories, emails, and other documents. It provides a unified CLI for rapid knowledge retrieval, powered by **Sentence‑Transformers** embeddings and **Qdrant** vector storage.

---

## ✨ Highlights
- **Unified search** across code, documentation, and email threads.
- **Instant semantic ranking** with configurable repository boost and email weight.
- **Robust indexing pipeline** that chunk‑splits raw text, stores metadata, and uploads vector embeddings.
- **Zero‑configuration model loading** – the `Embedder` loads the Sentence‑Transformer only once per process.
- **CLI commands** for syncing, re‑indexing, debugging, and detailed retrieval diagnostics.
- **Extensible architecture** – easy to plug in new data sources or embedding models.

---

## 📦 Quick Start
```bash
# Clone the repo (already done)
cd "c:/Users/HP/Desktop/machine learning/Memory-os"

# Install dependencies (Python 3.10+ recommended)
uv pip install -r requirements.txt

# Create .env file (copy from .env.example) and add your Groq API keys, Composio token, etc.
cp .env.example .env

# Initialise SQLite DB and sync data sources
uv run main.py
# then inside the interactive shell:
#   sync-github   # pulls repository docs & README
#   reindex       # builds chunks and uploads embeddings
```

---

## 🛠️ Core Components
| Module | Purpose |
|--------|---------|
| `connectors/github.py` | Syncs GitHub repos, downloads README, `package.json`, `requirements.txt`, `pyproject.toml`, Docker files, etc. |
| `core/chunker.py` | Splits raw document text into overlapping chunks (800‑char size, 120‑char overlap) and stores them in the DB. |
| `core/embedder.py` | Wraps `SentenceTransformer` (`all‑MiniLM‑L6‑v2`). Loads the model **once** (singleton) and provides `embed_documents` / `embed_query`. |
| `core/vector_store.py` | Handles Qdrant collection creation, vector upload, semantic search, and helper debug commands. |
| `storage/db.py` | SQLite schema, CRUD for repositories, documents, emails, and chunk storage. |
| `main.py` | Interactive CLI entry point – routes commands like `semantic‑search`, `debug‑index`, `debug‑vector`, etc. |

---

## 🚀 Available CLI Commands
```
sync-github               # Pulls repository metadata & selected files
sync-gmail                # Pulls recent emails (via Composio)
reindex                   # Chunk, embed and upload all content to Qdrant
semantic-search <query>   # Perform a semantic search (default limit=5)
debug-retrieval <query>   # Show raw Qdrant hits with scores
debug-index <repo>        # Lists documents, chunk counts and total vectors for a repo
debug-vector <repo>        # Prints the first 5 stored chunks for a repo
vector-stats              # Shows Qdrant collection stats
stats                     # Shows DB counts for repos, docs, emails
exit                      # Quit the interactive shell
```

---

## ⚙️ Configuration
Environment variables (loaded from `.env`):
- `GROQ_API_KEY_1`, `GROQ_API_KEY_2` – two keys for automatic rotation on rate‑limit errors.
- `REPO_SCORE_BOOST` – multiplier for repository scores during ranked search (default `1.0`).
- `EMAIL_SCORE_WEIGHT` – multiplier for email scores during ranked search (default `1.0`).
- `DEBUG` – when set to `true`, the system logs full prompts, raw LLM responses and detailed retrieval diagnostics.

---

## 📊 Debugging & Diagnostics
- **`debug-index <repo>`** – prints a summary of all indexed documents, their chunk counts, and total vectors uploaded for the repository.
- **`debug-vector <repo>`** – fetches the first five stored Qdrant points (payload includes `repository_name`, `document_name`, `source_type`, `chunk_text`, `chunk_index`).
- All failures of the extractor now log to `logs/extraction_failures.log` with raw LLM output for easy inspection.

---

## 🧪 Testing
```bash
# Run unit tests (if any)
uv run pytest

# Verify that the README is indexed
uv run main.py
# inside the shell:
repo-readme Memory-OS   # should show the README content
semantic-search "personal knowledge operating system" --repos-only
```

---

## 🎨 Design Philosophy
Memory‑OS follows a **premium, glass‑morphic UI**‑style for any future web front‑ends: vibrant gradients, smooth micro‑animations, and modern typography (Inter). The CLI itself uses clear sections, emojis, and consistent formatting to deliver a delightful developer experience.

---

## 📜 License
This project is licensed under the **MIT License**.

---

*Happy knowledge hunting!*
