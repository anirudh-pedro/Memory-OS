# Core Systems

## Ingestion Pipeline (`core/pipeline.py`)

The pipeline orchestrates the flow of `Memory` objects from connectors into the storage systems.

**Steps:**
1. Scores the memory for importance.
2. Upserts raw data to SQLite `workspace_cache`.
3. Runs LLM GraphRAG Extraction (`core/extractor.py`).
4. Validates extracted entities via `MemoryQualityPipeline`.
5. Syncs nodes/edges to the Graph Store.
6. Chunks the text content.
7. Embeds text chunks and upserts to Qdrant.

## Extractor (`core/extractor.py`)

The `GraphRAGExtractor` handles passing text to the LLM (ChatGroq) and enforcing a structured output schema (Entities and Relationships). It gracefully handles HTTP 429/503 errors with exponential backoff and features a custom JSON repair heuristic to salvage malformed responses without discarding API calls.

## Embeddings (`core/embeddings.py`)

Memory-OS supports multiple embedding strategies:
*   **TF-IDF** (Default): A local, fast, frequency-based embedder that saves its vocabulary to `tfidf_model.json`.
*   **BGE/E5**: SentenceTransformer-based local embeddings.
*   **Nomic**: Remote API-based embeddings.

## Quality & Events (`memory/`)

*   **Quality (`memory/quality.py`)**: Responsible for data hygiene. Includes the `TechnologyClassifier` (canonicalizes "apache-kafka" to "kafka") and the `EntityValidator` (discards conversational noise).
*   **Events (`memory/events.py`)**: An Event Sourcing layer that logs major state changes (e.g., `PROJECT_CREATED`, `TECH_ADDED`) to the SQLite `events` table for auditing and tracking.
