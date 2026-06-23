# Memory-OS Codebase Guide 🧠

This guide serves as a high-level overview of the Memory-OS architecture and links to the comprehensive documentation system located in the `docs/` directory.

---

## 📚 Documentation Index

The complete documentation has been modularized for easier reading and maintenance. Please refer to the following sections:

*   **[Architecture & System Design](docs/architecture/overview.md)**: High-level diagrams and explanation of the 3-pillar storage strategy (SQLite, Qdrant, Neo4j).
*   **[Data Flow](docs/architecture/data-flow.md)**: Sequence diagrams explaining Ingestion, Hybrid Search Retrieval, and Deletion.
*   **[Installation & Setup](docs/setup/installation.md)**: Instructions for setting up the local environment, dependencies, and API keys.
*   **[Core Features](docs/features/core-features.md)**: Details on Multi-Source Sync, GraphRAG Extraction, and Hybrid Search.
*   **[CLI Usage](docs/cli/usage.md)**: A guide to the interactive CLI commands (`sync`, `stats`, `delete`, etc.).
*   **[Core Engine Systems](docs/core/systems.md)**: Deep dives into the Pipeline, Extractor, Embeddings, and Quality systems.
*   **[Composio Integrations](docs/integrations/connectors.md)**: Information on the GitHub, Gmail, Notion, and Calendar data connectors.
*   **[Development & Conventions](docs/development/conventions.md)**: Coding conventions, debugging tips, and testing strategies.
*   **[Ontology Reference](docs/reference/ontology.md)**: The strict Entity and Relationship types enforced by the GraphRAG system.

---

## 🏗️ Quick Architecture Overview

Memory-OS is a CLI-based Personal Knowledge Operating System. It syncs data from external platforms via Composio, extracts semantic and graph data using Groq LLMs, stores it in three complementary databases, and provides natural language query answering via hybrid retrieval.

```
GitHub, Gmail, Notion, Calendar
           ↓
    Composio Connectors (connectors/)
           ↓
      Sync Pipeline (core/pipeline.py)
     /      |      \
    v       v       v
SQLite    Qdrant   GraphRAG Extractor (core/extractor.py)
(Cache)  (Vectors)   ↓
                     Entity Validation & Resolution (memory/quality.py)
                     ↓
                   SQLite (metadata.db) & Neo4j (core/graph_store.py)
```

For detailed sequence diagrams, see the [Data Flow Documentation](docs/architecture/data-flow.md).

---

## 🔍 Documentation Audit Report

During the transition to the modular documentation system, a full codebase analysis was performed. The following findings identify technical debt, missing features, and areas for improvement.

### 1. Architectural Findings & Inconsistencies
*   **Missing Tests:** There is no standard `tests/` directory or configured `pytest` suite. Testing is currently relegated to ad-hoc scripts in `scratch/` which are throwing `ModuleNotFoundError` for `dotenv`.
*   **Deprecated Modules Referenced:** `core/pipeline.py` contains a comment indicating `memory/importance.py` is deprecated, and its scoring logic was inlined into the pipeline.
*   **Hardcoded Values:** Nomic embedder API key fetching (`NOMIC_API_KEY`) and LLM model selections (`GROQ_MODEL`) are mixed directly into core logic rather than being centralized in a config module.
*   **Error Handling in CLI:** In `main.py`, tool patching involves a highly complex dynamic schema modification (`patch_tool_schemas`) that could be fragile against future `pydantic` or `composio` updates.

### 2. Missing or Outdated Documentation
*   The original `README.md` lacked details on the new modular documentation system.
*   The exact mechanics of how Qdrant automatic dimension recovery works (triggering `scripts/reindex_all.py`) was not explicitly documented in the user-facing guides.

### 3. Technical Debt
*   **Testing Infrastructure**: The highest priority technical debt is the lack of unit and integration tests. The CLI interface (`main.py`) and the complex ingestion pipeline currently rely entirely on manual testing.
*   **Logging**: Logs are written to `logs/extraction_failures.log` explicitly within `extractor.py`, but standard system logs (via the `logging` module) are only printed to `stdout`. There is no rotating file handler for general system logs.

### 4. Improvement Opportunities
*   **Centralized Configuration**: Create a `core/config.py` using Pydantic Settings to manage all environment variables instead of scattering `os.getenv()` calls throughout the codebase.
*   **Test Suite Integration**: Set up a proper `pytest` environment with mocks for the Composio and Groq APIs to ensure the ingestion pipeline can be tested safely in CI/CD.
