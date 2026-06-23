# Core Features

## 1. Multi-Source Sync

Memory-OS pulls data from multiple external platforms into a unified local cache. It utilizes **Composio** to handle OAuth flows and API integrations.

Supported Connectors:
*   **GitHub**: Fetches repositories, issues, pull requests, and READMEs.
*   **Gmail**: Fetches recent emails and communication context.
*   **Notion**: Fetches workspace documentation pages.
*   **Google Calendar**: Fetches meeting and event schedules.

Run synchronization manually via the CLI:
```text
[default_session] You: sync
```

## 2. GraphRAG Extraction

Rather than just embedding text chunks, Memory-OS uses a Large Language Model (LLM) to extract structured **Entities** (People, Projects, Technologies) and **Relationships** (WORKS_ON, USES, DEPENDS_ON) from the raw text.

This is executed by the `GraphRAGExtractor` (`core/extractor.py`). It utilizes intelligent JSON repair, retry mechanisms for rate limits, and fallback strategies if tool calling is disabled.

## 3. Hybrid Search

When you ask Memory-OS a question, it doesn't rely on a single retrieval method. The `HybridSearcher` (`retrieval/searcher.py`) performs three concurrent queries:

1.  **Semantic (Vector) Search**: Qdrant vector database retrieves text chunks that have semantic similarity to the query.
2.  **Full-Text Search (FTS)**: SQLite FTS5 retrieves documents with exact keyword matches.
3.  **Graph Traversal**: The Graph DB (Neo4j or SQLite) retrieves direct and multi-hop neighbor connections related to the entities detected in the query.

These three contexts are merged into a single "Unified Context" block, which is then fed into the Groq LLM to produce a highly accurate answer.
