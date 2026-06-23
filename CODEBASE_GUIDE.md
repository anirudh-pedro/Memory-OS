# Memory-OS Codebase Guide 🧠

This guide provides a complete breakdown of the Memory-OS architecture and documents every file in the repository.

---

## 🏗️ Architecture Overview

Memory-OS is a CLI-based Personal Knowledge Operating System. It syncs data from external platforms, stores it in three complementary databases (SQLite, Qdrant, Neo4j), and provides natural language query answering via hybrid retrieval.

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

### Data Flow

1. **Ingestion**: Composio connectors fetch raw data → normalized into `Memory` objects → cached in SQLite `workspace_cache` → text chunks embedded and upserted to Qdrant → entities/relationships extracted by LLM → validated by quality pipeline → stored in SQLite entities table and Neo4j graph.
2. **Retrieval**: User query → vector similarity search (Qdrant) + full-text search (SQLite FTS5) + graph neighbor traversal (Neo4j/SQLite) → merged context → LLM generates answer.

---

## 📂 File Index

### Root Files

#### [main.py](main.py)
- **Role**: Single entry point and CLI orchestrator.
- **Description**: Initializes all core systems (database, embedder, vector store, graph store, LLM, Composio session), verifies external connections, and runs the interactive CLI loop. Handles commands: `sync`, `stats`, `delete --before`, and natural language queries.

#### [pyproject.toml](pyproject.toml)
- **Role**: Project configuration and dependency manifest.
- **Description**: Lists Python version requirements and dependencies (composio, langchain-groq, qdrant-client, neo4j, etc.) managed by `uv`.

---

### `core/` — Core Engine

#### [db.py](core/db.py)
- **Role**: SQLite connection manager and schema initializer.
- **Description**: Provides `DatabaseConnectionManager` which creates/migrates the `metadata.db` database. Runs `database/schema.sql` on startup and handles column migrations (e.g., adding `description`, `aliases_json`, `importance_score` columns).

#### [embeddings.py](core/embeddings.py)
- **Role**: TF-IDF text embedder with vocabulary persistence.
- **Description**: Implements `TFIDFEmbedder` with `fit()`, `embed_documents()`, and `embed_query()` methods. Persists vocabulary to `tfidf_model.json`. Provides `get_embedder()` factory that loads persisted state on startup without refitting.

#### [vector_store.py](core/vector_store.py)
- **Role**: Qdrant vector store wrapper.
- **Description**: Manages the Qdrant collection lifecycle: creation, dimension verification, metadata persistence, chunk upsert, similarity search, and date-based deletion. Supports automatic recovery when dimensions mismatch.

#### [graph_store.py](core/graph_store.py)
- **Role**: Graph database abstraction layer.
- **Description**: Defines `BaseGraphStore` interface and two implementations: `SQLiteGraphStore` (local fallback using `metadata.db`) and `Neo4jGraphStore` (production graph). Both support `add_node()`, `add_relationship()`, `search_nodes()`, `get_neighbors()`, and `delete_before()`.

#### [extractor.py](core/extractor.py)
- **Role**: LLM-powered entity/relationship extraction.
- **Description**: `GraphRAGExtractor` prompts the LLM to extract structured entities and relationships from text chunks. Supports optional tool calling (`USE_TOOL_CALLING` env var). Features JSON repair for malformed responses, retries only on network/rate-limit errors (not parse failures), logs raw LLM responses, and writes failures to `logs/extraction_failures.log`.

#### [pipeline.py](core/pipeline.py)
- **Role**: Ingestion pipeline orchestrator.
- **Description**: `IngestionPipeline.run_ingestion()` processes `Memory` objects: caches in SQLite, splits into chunks, embeds and upserts to Qdrant, runs GraphRAG extraction, validates entities through the quality pipeline, and stores clean entities/relationships in the graph store.

#### [models.py](core/models.py)
- **Role**: Data model definitions.
- **Description**: Defines `Memory`, `MemoryChunk`, `Entity`, `Relationship`, and `GraphExtractionResult` dataclasses/Pydantic models used throughout the system.

---

### `connectors/` — Data Source Connectors

#### [base.py](connectors/base.py)
- **Role**: Abstract base class for connectors.
- **Description**: Defines `BaseConnector` with the `sync(session)` interface that all connectors implement.

#### [github.py](connectors/github.py)
- **Role**: GitHub data connector.
- **Description**: Fetches authenticated user profile, repositories, READMEs, issues, and pull requests via Composio GitHub toolkit. Returns normalized `Memory` objects.

#### [gmail.py](connectors/gmail.py)
- **Role**: Gmail data connector.
- **Description**: Fetches recent emails via Composio Gmail toolkit, extracts sender/recipient metadata, subjects, and body content.

#### [notion.py](connectors/notion.py)
- **Role**: Notion data connector.
- **Description**: Fetches workspace users and pages via Composio Notion toolkit.

#### [calendar.py](connectors/calendar.py)
- **Role**: Google Calendar data connector.
- **Description**: Fetches calendar list and events via Composio Calendar toolkit.

---

### `memory/` — Quality & Event Systems

#### [quality.py](memory/quality.py)
- **Role**: Entity validation, classification, and resolution.
- **Description**: Contains `EntityValidator` (filters noise/placeholder entities), `TechnologyClassifier` (canonicalizes technology names), `ProjectClassifier` (LLM-based project validation), `ProjectDetector` (automatic project linking), and `MemoryQualityPipeline` (orchestrates all quality checks).

#### [events.py](memory/events.py)
- **Role**: Event sourcing logger.
- **Description**: `EventStore` logs system events (entity creation, technology addition, project detection) to the SQLite `events` table with typed `EventType` enum.

---

### `retrieval/` — Search & Retrieval

#### [searcher.py](retrieval/searcher.py)
- **Role**: Unified hybrid search engine.
- **Description**: `HybridSearcher.search_hybrid()` runs three parallel searches (vector similarity via Qdrant, full-text via SQLite FTS5, graph neighbors via graph store) and returns merged results for LLM context building.

---

### `ontology/` — Type Definitions

#### [entity_types.py](ontology/entity_types.py)
- **Role**: Entity type enum.
- **Description**: Defines `EntityType` enum: Person, Project, Technology, Task, Document, Repository, Event, Organization, Decision, Skill.

#### [relationship_types.py](ontology/relationship_types.py)
- **Role**: Relationship type enum.
- **Description**: Defines `RelationshipType` enum: WORKS_ON, USES, DEPENDS_ON, MENTIONED_IN, CREATED, RELATED_TO, ATTENDS, IMPLEMENTS, CONTRIBUTES_TO, PART_OF, DISCUSSED_IN, DERIVED_FROM, MENTIONS.

---

### `database/` — Schema

#### [schema.sql](database/schema.sql)
- **Role**: SQLite schema definition.
- **Description**: Defines tables (`entities`, `relationships`, `workspace_cache`, `events`, `sync_metadata`), FTS5 virtual tables for full-text search, and triggers for automatic FTS sync.

---

### `scripts/` — Maintenance Scripts

#### [reindex_all.py](scripts/reindex_all.py)
- **Role**: Vector store reindexing script.
- **Description**: Reads all workspace cache entries and entities from SQLite, refits the embedder (or reuses existing vocabulary), recreates the Qdrant collection, and uploads all vectors. Called automatically during dimension mismatch recovery.

---

### `scratch/` — Development & Test Scripts

#### [test_extractor.py](scratch/test_extractor.py)
- **Role**: Live extraction test.
- **Description**: Tests the `GraphRAGExtractor` against the real Groq API with a sample text input. Verifies template rendering, API invocation, and parsing.

#### [test_extractor_failures.py](scratch/test_extractor_failures.py)
- **Role**: Extraction failure unit tests.
- **Description**: Uses `unittest.mock` to simulate clean JSON, markdown-wrapped JSON, and completely malformed responses. Verifies JSON repair, no-retry-on-parse-failure behavior, and `logs/extraction_failures.log` file writing.

---

### Data Files

| File | Purpose |
| :--- | :--- |
| `metadata.db` | SQLite database (entities, relationships, cache, events, sync metadata) |
| `tfidf_model.json` | Persisted TF-IDF embedder vocabulary |
| `qdrant_storage/` | Persistent Qdrant vector database storage |
| `logs/` | Extraction failure logs and diagnostics |
