# Architecture Overview

Memory-OS is a CLI-based Personal Knowledge Operating System (PKOS). Its primary function is to ingest data from multiple external sources (GitHub, Gmail, Notion, Google Calendar), extract semantic and graph representations, and serve as an intelligent, locally-first search engine via LLM-powered natural language queries.

## High-Level System Architecture

```mermaid
flowchart TD
    subgraph Data Sources
        GH[GitHub]
        GM[Gmail]
        NO[Notion]
        GC[Google Calendar]
    end

    subgraph Connectors
        C_GH[GitHub Connector]
        C_GM[Gmail Connector]
        C_NO[Notion Connector]
        C_GC[Calendar Connector]
    end

    subgraph Core Engine
        Pipe[Ingestion Pipeline]
        Ext[GraphRAG Extractor]
        Quality[Quality Pipeline]
        Search[Hybrid Searcher]
    end

    subgraph Storage
        SQLite[(SQLite Cache & Metadata)]
        Qdrant[(Qdrant Vector DB)]
        Neo4j[(Neo4j Graph DB)]
    end

    GH --> C_GH
    GM --> C_GM
    NO --> C_NO
    GC --> C_GC

    C_GH --> Pipe
    C_GM --> Pipe
    C_NO --> Pipe
    C_GC --> Pipe

    Pipe -->|Raw data| SQLite
    Pipe -->|Text chunks| Qdrant
    Pipe -->|Content| Ext

    Ext -->|Extracted Graph Data| Quality
    Quality -->|Clean Nodes/Edges| SQLite
    Quality -->|Clean Nodes/Edges| Neo4j

    User[User CLI Query] --> Search
    Search -->|FTS| SQLite
    Search -->|Semantic| Qdrant
    Search -->|Neighbors| Neo4j
    Search -->|Merged Context| LLM[ChatGroq LLM]
    LLM --> User
```

## Three-Pillar Storage Strategy

Memory-OS utilizes three distinct storage technologies to power its retrieval system:

1.  **SQLite (`metadata.db`)**:
    *   Serves as the raw data cache (`workspace_cache`).
    *   Maintains the canonical record of Entities and Relationships (acting as a local graph fallback if Neo4j is offline).
    *   Provides Full-Text Search (FTS5) capabilities over raw documents.
    *   Logs system events via the Event Sourcing layer.
2.  **Qdrant**:
    *   Stores embedded document chunks.
    *   Enables dense vector similarity search to find semantically related context.
    *   Supports dynamic embedder models (TF-IDF, BGE, E5, Nomic).
3.  **Neo4j** (Optional but recommended):
    *   Provides native, highly-performant graph traversals.
    *   Stores validated nodes (Entities) and edges (Relationships).
    *   Enables multi-hop neighbor discovery during retrieval.
