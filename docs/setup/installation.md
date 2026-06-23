# Installation

This guide will walk you through setting up Memory-OS locally.

## Prerequisites

1.  **Python**: Version 3.12 or higher.
2.  **uv**: The modern Python package manager (`pip install uv`).
3.  **API Keys**:
    *   Composio API Key (for external connectors)
    *   Groq API Key (for LLM interactions)
4.  **Database Services**:
    *   Qdrant (Vector DB)
    *   Neo4j (Graph DB) - *Optional, but highly recommended. SQLite is used as a fallback.*

## Step 1: Install Dependencies

Clone the repository and install dependencies using `uv`:

```bash
git clone <repository_url>
cd Memory-OS
uv sync
```

## Step 2: Configure Environment Variables

Create a `.env` file in the root of the project by copying the provided example (if one exists) or using the structure below:

```env
# Required
COMPOSIO_API_KEY=your_composio_api_key_here
GROQ_API_KEY=your_groq_api_key_here

# LLM Configuration
GROQ_MODEL=llama-3.3-70b-versatile

# Neo4j Graph Database (Optional)
# If omitted, Memory-OS falls back to using the local metadata.db SQLite file.
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_secure_password

# Vector Embedder Configuration (Optional)
# Options: tfidf (default), bge, nomic, e5
EMBEDDER_TYPE=tfidf
# If using Nomic embedder:
NOMIC_API_KEY=your_nomic_key_here

# Advanced Execution Flags
# Enable structured output (function calling) for GraphRAG extraction
USE_TOOL_CALLING=false
```

## Step 3: Run the System

To start the CLI interface, run:

```bash
uv run main.py
```

### First-Run Authentication
Upon your first run, the CLI will verify connections to the configured integrations (GitHub, Gmail, Notion, Calendar). If any are disconnected, it will output a Composio redirect URL. Open this URL in your browser, authenticate, and then return to the CLI.
