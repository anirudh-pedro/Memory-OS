# Data Flow

This document outlines how data moves through the Memory-OS system, from ingestion to query answering.

## 1. Ingestion Lifecycle

The ingestion process is orchestrated by the `IngestionPipeline` (`core/pipeline.py`).

```mermaid
sequenceDiagram
    participant CLI
    participant Connectors
    participant Pipeline
    participant SQLite
    participant Extractor
    participant Quality
    participant GraphStore
    participant VectorStore

    CLI->>Connectors: sync()
    Connectors-->>CLI: List of Memory objects
    CLI->>Pipeline: run_ingestion(memories)

    loop For each Memory
        Pipeline->>SQLite: Save raw Memory (upsert)
        Pipeline->>Extractor: extract(Memory.content)
        Extractor-->>Pipeline: Raw Entities & Relationships

        Pipeline->>Quality: process_entity()
        Quality-->>Pipeline: Canonicalized Entity

        Pipeline->>GraphStore: add_node() / add_relationship()

        Pipeline->>Pipeline: chunk_text()
        Pipeline->>VectorStore: embed and upsert_chunks()
    end

    Pipeline->>Quality: run_full_consolidation()
```

## 2. Retrieval Lifecycle (Hybrid Search)

When a user asks a question, the `HybridSearcher` (`retrieval/searcher.py`) runs queries across all databases simultaneously.

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant Searcher
    participant SQLite
    participant VectorStore
    participant GraphStore
    participant LLM

    User->>CLI: "What is Memory-OS?"
    CLI->>Searcher: search_hybrid("What is Memory-OS?")

    par FTS Search
        Searcher->>SQLite: MATCH query on FTS table
    and Semantic Search
        Searcher->>VectorStore: Similarity search on query vector
    and Graph Traversal
        Searcher->>GraphStore: Find direct and multi-hop neighbors
    end

    Searcher->>Searcher: Merge and deduplicate results
    Searcher-->>CLI: Unified Context

    CLI->>LLM: Prompt with Unified Context + User Query
    LLM-->>CLI: Natural language response
    CLI-->>User: "Memory-OS is..."
```

## 3. Deletion Lifecycle

When a user runs `delete --before YYYY-MM-DD`, the system prunes old data across all stores.

1.  **SQLite**: Deletes rows from `workspace_cache` and `events` where timestamps are older than the specified date.
2.  **Graph Store**: Deletes nodes older than the date. (Cascading deletes automatically handle orphaned relationships in both SQLite and Neo4j).
3.  **Vector Store**: Uses Qdrant filters to delete points based on the `last_synced` metadata payload.
