import os
import sys
import argparse
import logging
import re
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv

# Core Modules & Pipeline
from core.db import DatabaseConnectionManager
from core.embeddings import get_embedder
from core.vector_store import QdrantVectorStore
from core.graph_store import SQLiteGraphStore, Neo4jGraphStore
from core.extractor import GraphRAGExtractor
from core.pipeline import IngestionPipeline
from core.models import Memory
from retrieval.searcher import HybridSearcher

# Connectors
from connectors.github import GitHubConnector
from connectors.gmail import GmailConnector
from connectors.notion import NotionConnector
from connectors.calendar import CalendarConnector

# Composio & LangChain
from composio import Composio, SESSION_PRESET_DIRECT_TOOLS
from composio_langchain import LangchainProvider
from langchain_groq import ChatGroq

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("memory_os")

load_dotenv()

# Force standard output to UTF-8 to handle Unicode characters smoothly on Windows
sys.stdout.reconfigure(encoding='utf-8')

db_path = "metadata.db"

# 1. Initialize core system storage & embeddings
db_manager = DatabaseConnectionManager(db_path=db_path)
vector_store = QdrantVectorStore()
embedder = get_embedder()

print("="*40)
print(f"Embedder Loaded: {embedder.__class__.__name__}")
print(f"Vocabulary Size: {len(embedder.vocabulary)}")
print(f"Dimension: {getattr(embedder, 'dimension', len(embedder.vocabulary))}")
print(f"Model Version: {getattr(embedder, 'version', 'N/A')}")
print("="*40)

# Dynamic Graph DB auto-switching based on env variables
neo4j_uri = os.getenv("NEO4J_URI")
if neo4j_uri:
    logger.info("Connecting to Neo4j Graph Database...")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    graph_store = Neo4jGraphStore(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
else:
    logger.info("Connecting to local SQLite Graph Store...")
    graph_store = SQLiteGraphStore(db_path)

# Initialize Search, Extractor
searcher = HybridSearcher(db_manager, vector_store, embedder, graph_store)

# Startup check for Qdrant Collection verification, metadata matching, and auto-recovery
try:
    dimension = getattr(embedder, "dimension", len(embedder.vocabulary))
    if dimension > 0:
        exists = vector_store.collection_exists()
        mismatch = False
        mismatch_reason = ""
        
        # 1. Load persisted collection metadata
        meta = vector_store.load_metadata()
        if not exists:
            mismatch = True
            mismatch_reason = "Collection does not exist"
        else:
            # Check actual collection dimension
            try:
                info = vector_store.client.get_collection(vector_store.collection_name)
                current_dim = info.config.params.vectors.size
                if current_dim != dimension:
                    mismatch = True
                    mismatch_reason = f"Actual collection dimension mismatch ({current_dim} vs {dimension})"
            except Exception as ex:
                mismatch = True
                mismatch_reason = f"Failed to retrieve collection info: {ex}"
                
            # Compare persisted metadata dimension
            if not mismatch and meta:
                meta_dim = meta.get("dimension")
                if meta_dim != dimension:
                    mismatch = True
                    mismatch_reason = f"Metadata dimension mismatch ({meta_dim} vs {dimension})"

        if mismatch:
            logger.warning(f"Qdrant collection verification failed: {mismatch_reason}. Triggering automatic recovery...")
            try:
                if exists:
                    try:
                        vector_store.client.delete_collection(vector_store.collection_name)
                        logger.info(f"Deleted outdated collection '{vector_store.collection_name}'.")
                    except Exception as e:
                        logger.warning(f"Failed to delete collection during recovery: {e}")
                
                vector_store.initialize_collection(dimension=dimension, force_recreate=True, embedder=embedder)
                
                # Reindex all cached entries and upload vectors using currently loaded embedder without refitting
                from scripts.reindex_all import run_migration_and_reindex
                run_migration_and_reindex(vector_store=vector_store, embedder=embedder, refit=False)
                
                embedder_type = os.getenv("EMBEDDER_TYPE", "tfidf").lower()
                version = getattr(embedder, "version", f"{embedder_type}_{dimension}")
                vector_store.save_metadata(embedder_type, dimension, version)
                
                logger.info("Automatic vector store recovery completed successfully!")
            except Exception as recovery_err:
                logger.error(f"Automatic recovery failed: {recovery_err}")
                raise recovery_err
        else:
            logger.info("Qdrant collection exists and dimensions are verified. Loaded successfully.")
    else:
        logger.info("Embedder vocabulary is empty on launch. Dimension check deferred until fit is performed.")
except Exception as e:
    logger.error("="*80)
    logger.error("🚨 WARNING: Persistent vector store initialization or recovery failed! 🚨")
    logger.error(f"Reason: {e}")
    logger.error("Vector retrieval mode is now DISABLED. The assistant will fallback to Graph & Full-Text Search (FTS).")
    logger.error("To resolve this issue manually, please ensure Qdrant is running and run the migration script:")
    logger.error("    uv run python scripts/reindex_all.py")
    logger.error("="*80)
    vector_store.vector_retrieval_enabled = False

# 2. LLM Setup
llm = ChatGroq(
    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.0
)

# GraphRAG Extractor
extractor = GraphRAGExtractor(llm, graph_store)

# Ingestion Pipeline
pipeline = IngestionPipeline(db_manager, vector_store, embedder, graph_store=graph_store, extractor=extractor)

# 3. Composio Session & Toolkits Setup
composio = Composio(provider=LangchainProvider())
session = composio.create(
    user_id="user_123",
    toolkits=["github", "googlecalendar", "notion", "gmail"],
    tools={
        "github": {
            "enable": [
                "GITHUB_GET_THE_AUTHENTICATED_USER",
                "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
                "GITHUB_GET_A_REPOSITORY",
                "GITHUB_GET_A_REPOSITORY_README",
                "GITHUB_LIST_REPOSITORY_ISSUES",
                "GITHUB_LIST_PULL_REQUESTS",
                "GITHUB_LIST_REPOSITORY_PROJECTS",
                "GITHUB_LIST_USER_PROJECTS",
                "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER",
                "GITHUB_CREATE_AN_ISSUE",
            ]
        },
        "googlecalendar": {
            "enable": [
                "GOOGLECALENDAR_LIST_CALENDARS",
                "GOOGLECALENDAR_CREATE_EVENT",
                "GOOGLECALENDAR_QUICK_ADD",
            ]
        },
        "notion": {
            "enable": [
                "NOTION_LIST_USERS",
                "NOTION_SEARCH_NOTION_PAGE",
                "NOTION_CREATE_NOTION_PAGE",
                "NOTION_APPEND_TEXT_BLOCKS",
            ]
        },
        "gmail": {
            "enable": [
                "GMAIL_FETCH_EMAILS",
                "GMAIL_SEND_EMAIL",
            ]
        }
    },
    session_preset=SESSION_PRESET_DIRECT_TOOLS,
)
tools = session.tools()

# Dynamic patch function for optional schema parameters that default to None
def patch_tool_schemas(tools_list):
    import typing
    from pydantic import create_model, BaseModel
    
    def simplify_type(annotation):
        if annotation is None:
            return None
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return dict
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        if origin is not None and args:
            has_model = False
            for a in args:
                if isinstance(a, type) and issubclass(a, BaseModel):
                    has_model = True
                elif typing.get_origin(a) is not None:
                    has_model = True
            if has_model:
                return dict
        return annotation

    for t in tools_list:
        if t.args_schema is None:
            continue
        patched_fields = {}
        for name, field in t.args_schema.model_fields.items():
            annotation = field.annotation
            default = field.default
            
            annotation = simplify_type(annotation)
            
            if default is None:
                args = typing.get_args(annotation)
                if type(None) not in args:
                    if args:
                        annotation = typing.Union[annotation, None]
                    else:
                        annotation = typing.Optional[annotation]
            patched_fields[name] = (annotation, default)
        
        t.args_schema = create_model(t.args_schema.__name__, **patched_fields)

patch_tool_schemas(tools)

def ensure_connections():
    """Ensure required external auth connections are valid."""
    toolkits_info = session.toolkits()
    for tk_slug in ["github", "gmail", "notion", "googlecalendar"]:
        tk = next((t for t in toolkits_info.items if t.slug == tk_slug), None)
        if not tk or not (tk.connection and tk.connection.is_active):
            print(f"\n[{tk_slug.upper()}] connection is not active.")
            print(f"Initiating authentication flow for {tk_slug}...")
            connection_req = session.initiate_connection(toolkit_slug=tk_slug)
            print(f"Please open this URL in your browser to complete login:\n{connection_req.redirect_url}\n")
            connection_req.wait_for_connection()
            print(f"[{tk_slug.upper()}] connection established successfully!\n")
        else:
            print(f"[{tk_slug.upper()}] connection is active.")

def update_sync_metadata(db_manager, stats_dict):
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO sync_metadata (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            ("last_sync_time", datetime.now().isoformat())
        )
        cursor.execute(
            "INSERT INTO sync_metadata (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            ("last_sync_stats", json.dumps(stats_dict))
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to update sync metadata: {e}")
    finally:
        conn.close()

def show_stats(db_manager, vector_store, graph_store):
    print("\n" + "="*45)
    print("🧠 PKOS KNOWLEDGE METRICS & DIAGNOSTICS 🧠")
    print("="*45)
    
    # 1. SQLite stats
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM workspace_cache")
        total_cache = cursor.fetchone()[0]
        
        cursor.execute("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type")
        entity_types = {row[0]: row[1] for row in cursor.fetchall()}
        
        cursor.execute("SELECT COUNT(*) FROM relationships")
        total_rels = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM events")
        total_events = cursor.fetchone()[0]
        
        cursor.execute("SELECT value FROM sync_metadata WHERE key = 'last_sync_time'")
        row = cursor.fetchone()
        last_sync = row[0] if row else "Never"
    except sqlite3.Error as e:
        logger.error(f"Failed to fetch SQLite stats: {e}")
        total_cache = 0
        entity_types = {}
        total_rels = 0
        total_events = 0
        last_sync = "Unknown"
    finally:
        conn.close()
        
    print(f"Last Synchronization: {last_sync}")
    print(f"Total Cached Documents: {total_cache}")
    print(f"Total Logged Events: {total_events}")
    print("\nKnowledge Graph (SQLite relational representation):")
    print(f"  • Total Entities: {sum(entity_types.values())}")
    for etype, count in sorted(entity_types.items()):
        print(f"    - {etype}: {count}")
    print(f"  • Total Relationships: {total_rels}")
    
    # 2. Qdrant stats
    if getattr(vector_store, "vector_retrieval_enabled", True) and vector_store.collection_exists():
        try:
            info = vector_store.client.get_collection(vector_store.collection_name)
            vector_count = info.points_count
        except Exception:
            vector_count = "Error"
    else:
        vector_count = "Disabled"
    print(f"\nVector DB (Qdrant similarity representation):")
    print(f"  • Total Vectors: {vector_count}")
    
    # 3. Neo4j stats (if enabled)
    if isinstance(graph_store, Neo4jGraphStore):
        try:
            nodes = graph_store.get_all_nodes()
            rels = graph_store.get_all_relationships()
            neo4j_nodes_count = len(nodes)
            neo4j_rels_count = len(rels)
        except Exception:
            neo4j_nodes_count = "Error"
            neo4j_rels_count = "Error"
        print(f"\nExternal Graph (Neo4j native representation):")
        print(f"  • Total Nodes: {neo4j_nodes_count}")
        print(f"  • Total Edges: {neo4j_rels_count}")
        
    print("="*45 + "\n")

def handle_delete(date_str: str, db_manager, vector_store, graph_store):
    print(f"Pruning memories and graph elements synced before '{date_str}'...")
    
    # 1. SQLite database
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    deleted_cache = 0
    deleted_events = 0
    try:
        # Delete workspace cache
        cursor.execute("DELETE FROM workspace_cache WHERE last_synced < ?", (date_str,))
        deleted_cache = cursor.rowcount
        
        # Delete event sourcing events
        cursor.execute("DELETE FROM events WHERE created_at < ?", (date_str,))
        deleted_events = cursor.rowcount
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to delete SQLite data: {e}")
    finally:
        conn.close()

    # 2. SQLite / Neo4j Graph Store
    graph_deleted = graph_store.delete_before(date_str)
    
    # 3. Qdrant Vector Store
    vector_deleted = vector_store.delete_before(date_str)
    
    print("Pruning completed:")
    print(f"  • Removed {deleted_cache} records from SQLite cache")
    print(f"  • Removed {deleted_events} event logs")
    print(f"  • Graph Store cleanup: {'Success' if graph_deleted else 'Failed'}")
    print(f"  • Vector Store cleanup: {'Success' if vector_deleted else 'Failed'}")

def query_answering(query: str, searcher: HybridSearcher, llm: ChatGroq):
    results = searcher.search_hybrid(query, limit=5)
    
    # Format graph context
    graph_context = ""
    entities = results.get("graph", {}).get("entities", [])
    relationships = results.get("graph", {}).get("relationships", [])
    
    if entities:
        graph_context += "Matched Entities:\n"
        for ent in entities:
            graph_context += f"- {ent['name']} ({ent['entity_type']}): {ent['description'] or 'No description'}\n"
    if relationships:
        graph_context += "\nMatched Relationships:\n"
        for rel in relationships:
            graph_context += f"- {rel['source']} --[{rel['relation_type']}]--> {rel['target']}\n"
            
    # Format vector context
    vector_context = ""
    vectors = results.get("vector", [])
    if vectors:
        vector_context += "Semantic Context Chunks:\n"
        for hit in vectors:
            payload = hit.get("payload", {})
            vector_context += f"- [{payload.get('source_app', 'Unknown')}] {payload.get('title', 'Untitled')}:\n  {payload.get('text', '')[:600]}\n"
            
    # Compile prompt
    prompt = (
        "You are Memory-OS, a high-performance Personal Knowledge Operating System.\n"
        "Answer the user's query based on the following unified context retrieved from the vector store and the knowledge graph. "
        "Be concise, clear, and direct. Do not assume or invent facts beyond what is in the context.\n\n"
        "=== Unified Context ===\n"
        f"{graph_context}\n"
        f"{vector_context}\n"
        "=======================\n\n"
        f"User Query: {query}\n\n"
        "Memory-OS Response:"
    )
    
    print("\nThinking...")
    try:
        response = llm.invoke(prompt)
        print(f"\nMemory-OS:\n{response.content}\n")
    except Exception as e:
        print(f"Failed to generate response: {e}")

# 7. Interactive CLI Loop execution
def run_cli():
    print("Verifying connections...")
    ensure_connections()

    thread_id = "default_session"
    print("\n" + "="*50)
    print("🧠 MEMORY-OS: A PERSONAL KNOWLEDGE OS 🧠")
    print(f"Active Session ID: {thread_id}")
    print("="*50)
    print("Commands:")
    print("  sync [--rebuild]          - Run ingestion connector pipeline sync")
    print("  delete --before <date>    - Prune records and nodes older than YYYY-MM-DD")
    print("  stats                     - Display database metrics and vector coverage")
    print("  exit / quit               - Exit the shell")
    print("="*50)

    while True:
        try:
            user_input = input(f"\n[{thread_id}] You: ").strip()
            user_input_lower = user_input.lower()
            
            if user_input_lower in ["exit", "quit"]:
                print("Goodbye!")
                vector_store.close()
                break
            
            if not user_input:
                continue
            
            # CLI Command: Ingestion Pipeline Sync
            if user_input_lower.startswith("sync") or user_input_lower.startswith("/sync"):
                parts = user_input_lower.split()
                rebuild = "--rebuild" in parts
                print("Running ingestion pipelines...")
                memories = []
                
                try:
                    print("Syncing GitHub...")
                    memories.extend(GitHubConnector().sync(session))
                except Exception as ex:
                    logger.error(f"GitHub Sync failed: {ex}")
                try:
                    print("Syncing Gmail...")
                    memories.extend(GmailConnector().sync(session))
                except Exception as ex:
                    logger.error(f"Gmail Sync failed: {ex}")
                try:
                    print("Syncing Notion...")
                    memories.extend(NotionConnector().sync(session))
                except Exception as ex:
                    logger.error(f"Notion Sync failed: {ex}")
                try:
                    print("Syncing Calendar...")
                    memories.extend(CalendarConnector().sync(session))
                except Exception as ex:
                    logger.error(f"Calendar Sync failed: {ex}")
                
                if memories:
                    ingested = pipeline.run_ingestion(memories, rebuild=rebuild)
                    print(f"Sync complete. Ingested {ingested} memory records into OS.")
                    stats_dict = {
                        "synced_at": datetime.now().isoformat(),
                        "memories_synced": len(memories),
                        "memories_ingested": ingested
                    }
                    update_sync_metadata(db_manager, stats_dict)
                else:
                    print("Sync complete. No new memories found.")
                continue

            # CLI Command: Delete before date
            if "delete --before" in user_input_lower:
                match = re.search(r"delete\s+--before\s+(\d{4}-\d{2}-\d{2})", user_input_lower)
                if match:
                    date_str = match.group(1)
                    handle_delete(date_str, db_manager, vector_store, graph_store)
                else:
                    print("Invalid format. Use: delete --before YYYY-MM-DD")
                continue

            # CLI Command: Stats
            if user_input_lower in ["stats", "/stats"]:
                show_stats(db_manager, vector_store, graph_store)
                continue

            # Standard user queryanswering via Hybrid Search & ChatGroq
            query_answering(user_input, searcher, llm)
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            vector_store.close()
            break
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memory-OS Engine CLI Engine")
    args, unknown = parser.parse_known_args()
    run_cli()
