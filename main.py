import os
import sys
import argparse
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn
import sqlite3
import json
from datetime import datetime

# Core Modules & Pipeline
from core.db import DatabaseConnectionManager
from core.embeddings import LocalTFIDFEmbedder
from core.vector_store import QdrantVectorStore
from core.graph_store import SQLiteGraphStore, Neo4jGraphStore
from core.extractor import GraphRAGExtractor
from core.pipeline import IngestionPipeline
from core.models import Memory

# Retrieval & Assistant
from retrieval.search import HybridSearcher
from assistant.agent import PersonalAssistantBuilder
from api.routes import create_router

# Connectors
from connectors.github import GitHubConnector
from connectors.gmail import GmailConnector
from connectors.notion import NotionConnector
from connectors.calendar import CalendarConnector

# Composio & LangChain
from composio import Composio, SESSION_PRESET_DIRECT_TOOLS
from composio_langchain import LangchainProvider
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("memory_os")

load_dotenv()

# Force standard output to UTF-8 to handle Unicode characters smoothly on Windows
sys.stdout.reconfigure(encoding='utf-8')

db_path = "memory.db"

# 1. Initialize core system storage & embeddings
db_manager = DatabaseConnectionManager(db_path=db_path)
vector_store = QdrantVectorStore()
embedder = LocalTFIDFEmbedder()

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

# Initialize Search, Extractor, Pipeline
searcher = HybridSearcher(db_manager, vector_store, embedder, graph_store)
pipeline = IngestionPipeline(db_manager, vector_store, embedder, graph_store=graph_store)

# Fit embedder on launch using existing db cache to keep queries operational
try:
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title, content FROM workspace_cache")
    cache_rows = cursor.fetchall()
    cursor.execute("SELECT name, entity_type, description, properties_json FROM entities")
    entity_rows = cursor.fetchall()
    conn.close()
    
    existing_docs = []
    for row in cache_rows:
        title = row["title"] or ""
        content = row["content"] or ""
        existing_docs.append(f"{title} {content}")
        
    for row in entity_rows:
        name = row["name"] or ""
        entity_type = row["entity_type"] or ""
        desc = row["description"] or ""
        props = row["properties_json"] or "{}"
        existing_docs.append(f"{name} {entity_type} {desc} {props}")
        
    if existing_docs:
        embedder.fit(existing_docs)
        
    # Startup check for Qdrant Collection verification & loading
    dimension = len(embedder.vocabulary)
    if dimension > 0:
        if not vector_store.collection_exists():
            logger.info("Qdrant collection 'memory_os' does not exist on launch. Initializing collection and performing auto-reindexing...")
            from scripts.reindex_all import run_migration_and_reindex
            run_migration_and_reindex(vector_store=vector_store)
        else:
            try:
                info = vector_store.client.get_collection(vector_store.collection_name)
                current_dim = info.config.params.vectors.size
                if current_dim != dimension:
                    logger.info(f"Qdrant collection 'memory_os' dimension mismatch ({current_dim} vs {dimension}). Reinitializing and reindexing...")
                    from scripts.reindex_all import run_migration_and_reindex
                    run_migration_and_reindex(vector_store=vector_store)
                else:
                    logger.info("Qdrant collection 'memory_os' exists with correct dimension. Loaded successfully.")
            except Exception as ex:
                logger.warning(f"Error checking startup collection info: {ex}. Reindexing...")
                from scripts.reindex_all import run_migration_and_reindex
                run_migration_and_reindex(vector_store=vector_store)
except Exception as e:
    logger.warning(f"Could not perform baseline embedding fit or startup Qdrant collection check: {e}")

# 2. LLM Setup
llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY")
)

# GraphRAG Extractor
extractor = GraphRAGExtractor(llm, graph_store)

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
    from pydantic import create_model
    for t in tools_list:
        # Prune tool description
        if t.description:
            first_sentence = t.description.split(".")[0].split(" - ")[0]
            t.description = first_sentence[:100].strip()
            
        if t.args_schema is None:
            continue
        patched_fields = {}
        for name, field in t.args_schema.model_fields.items():
            annotation = field.annotation
            default = field.default
            
            # Prune field description to reduce token count
            if hasattr(field, "description") and field.description:
                field.description = field.description.split(".")[0][:50].strip()
                
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

# 4. Agent Graph Compilation
with SqliteSaver.from_conn_string(db_path) as checkpointer:
    agent_builder = PersonalAssistantBuilder(
        llm=llm,
        tools=tools,
        graph_store=graph_store,
        searcher=searcher,
        extractor=extractor,
        db_path=db_path
    )
    agent_graph = agent_builder.build_graph()

# 5. FastAPI Instance Setup
app = FastAPI(title="Memory-OS API", description="Personal AI Memory OS Backend.")
router = create_router(
    agent_graph=agent_graph,
    session=session,
    db_manager=db_manager,
    vector_store=vector_store,
    embedder=embedder,
    graph_store=graph_store,
    pipeline=pipeline,
    llm=llm
)
app.include_router(router)


# 6. Connection Validation
def ensure_connections():
    toolkits_to_check = ["github", "googlecalendar", "notion", "gmail"]
    toolkits_info = session.toolkits()
    for tk_slug in toolkits_to_check:
        tk = next((t for t in toolkits_info.items if t.slug == tk_slug), None)
        if not tk or not (tk.connection and tk.connection.is_active):
            print(f"[{tk_slug.upper()}] connection is not active. Initiating authorization...")
            connection_req = session.authorize(tk_slug)
            print(f"\n[ACTION REQUIRED] Please authorize Composio to access your {tk_slug} account by visiting this URL:")
            print(f"--> {connection_req.redirect_url}\n")
            print("Waiting for you to complete authorization in your browser...")
            connection_req.wait_for_connection()
            print(f"[{tk_slug.upper()}] connection established successfully!\n")
        else:
            print(f"[{tk_slug.upper()}] connection is active.")


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
    print("  /clear                    - Clear current session chat history")
    print("  /session <id>             - Switch to/create a different session")
    print("  /sync                     - Run ingestion connector pipeline sync")
    print("  /project <name>           - Render project dashboard context (Project Brain)")
    print("  /timeline <start> <end>   - Render activity timeline logs")
    print("  /explore <ent1> <ent2>    - Render path links between two entities")
    print("  /graph                    - Render all graph nodes and edges")
    print("  /graph-quality            - Render Knowledge Graph quality metrics (Avg Node Degree)")
    print("  /debug-retrieval <query>  - Render retrieval diagnostic metrics (tokens, hits)")
    print("  exit / quit               - Exit the chat")
    print("="*50)

    while True:
        try:
            user_input = input(f"\n[{thread_id}] You: ").strip()
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            # CLI Command: Clear chat history
            if user_input.lower() == "/clear":
                conn = db_manager.get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
                cursor.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                cursor.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
                conn.commit()
                conn.close()
                print(f"Memory cleared for session '{thread_id}'.")
                continue
            
            # CLI Command: Switch session
            if user_input.startswith("/session "):
                parts = user_input.split(" ", 1)
                if len(parts) > 1 and parts[1].strip():
                    thread_id = parts[1].strip()
                    print(f"Switched to session '{thread_id}'.")
                else:
                    print("Invalid session ID.")
                continue

            # CLI Command: Ingestion Pipeline Sync
            if user_input.lower() == "/sync":
                print("Running ingestion pipelines...")
                memories = []
                
                # Fetch standard connectors
                print("Syncing GitHub...")
                memories.extend(GitHubConnector().sync(session))
                print("Syncing Gmail...")
                memories.extend(GmailConnector(llm=llm, graph_store=graph_store).sync(session))
                print("Syncing Notion...")
                memories.extend(NotionConnector().sync(session))
                print("Syncing Calendar...")
                memories.extend(CalendarConnector().sync(session))
                
                if memories:
                    ingested = pipeline.run_ingestion(memories)
                    print(f"Sync complete. Ingested {ingested} memory records into OS.")
                else:
                    print("Sync complete. No new memories found.")
                continue

            # CLI Command: Project Brain summary
            if user_input.startswith("/project "):
                parts = user_input.split(" ", 1)
                if len(parts) > 1 and parts[1].strip():
                    project_name = parts[1].strip()
                    node = graph_store.get_node(project_name)
                    if not node:
                        print(f"Project '{project_name}' not found in Knowledge Graph.")
                        continue
                    
                    relationships = graph_store.get_multi_hop_relationships(project_name, depth=2)
                    
                    # Fetch database matches
                    conn = db_manager.get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT source_app, title, content, last_synced FROM workspace_cache WHERE title LIKE ? OR content LIKE ?",
                        (f"%{project_name}%", f"%{project_name}%")
                    )
                    cache_rows = cursor.fetchall()
                    conn.close()
                    
                    items = [
                        {
                            "source": r["source_app"],
                            "title": r["title"],
                            "content": r["content"],
                            "timestamp": r["last_synced"]
                        } for r in cache_rows
                    ]
                    
                    print("\nSynthesizing Project Brain with LLM...")
                    synthesis_prompt = (
                        f"You are the project intelligence synthesizer of Memory-OS.\n"
                        f"Compile a detailed, synthesized, and highly readable dashboard for the Project: '{project_name}'\n\n"
                        f"Project Type: {node.entity_type}\n"
                        f"Primary Description: {node.description}\n"
                        f"Properties: {node.properties}\n\n"
                        f"Knowledge Graph Connections:\n"
                        f"{json.dumps(relationships, indent=2)}\n\n"
                        f"Related Workspace Documents/Logs:\n"
                        f"{json.dumps(items[:10], indent=2)}\n\n"
                        f"Structure your response strictly under these headers:\n"
                        f"1. Overview (A synthetic description of the project state and relevance)\n"
                        f"2. Technologies Used (A structured list of frame/languages/vector DBs and links)\n"
                        f"3. Recent Activity Timeline (Chronological timeline of commits, emails, updates)\n"
                        f"4. Related Knowledge & Open Issues (Action items, decisions, discussions, or bugs)\n"
                        f"5. Dependencies & Links (Other projects, people, or orgs connected to it)\n"
                    )
                    
                    try:
                        synthesis_resp = llm.invoke(synthesis_prompt)
                        print(f"\n📊 === PROJECT BRAIN: {project_name.upper()} ===")
                        print(synthesis_resp.content)
                        print("="*50)
                    except Exception as e:
                        print(f"Failed to synthesize project brain: {e}")
                else:
                    print("Invalid project name.")
                continue

            # CLI Command: Graph Quality metrics
            if user_input.lower() in ["/quality", "/graph-quality"]:
                conn = db_manager.get_connection()
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM entities")
                total_nodes = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM relationships")
                total_rels = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'Project'")
                project_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'Person'")
                people_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'Technology'")
                tech_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT name, entity_type FROM entities")
                all_ents = cursor.fetchall()
                
                dup_candidates = []
                seen = set()
                for e1 in all_ents:
                    n1 = e1["name"].lower()
                    t1 = e1["entity_type"]
                    for e2 in all_ents:
                        n2 = e2["name"].lower()
                        t2 = e2["entity_type"]
                        if n1 != n2 and t1 == t2:
                            pair = tuple(sorted([e1["name"], e2["name"]]))
                            if pair not in seen:
                                if n1 in n2 or n2 in n1:
                                    dup_candidates.append(f"  • {e1['name']} <-> {e2['name']} ({t1})")
                                    seen.add(pair)
                                    
                placeholders_pattern = ["unknown", "null", "none", "test", "untitled", "<unknown_repository>", "<owner>/<repo>"]
                placeholders_found = [e["name"] for e in all_ents if any(p in e["name"].lower() for p in placeholders_pattern) or "<" in e["name"] or ">" in e["name"]]
                
                noise_found = [e["name"] for e in all_ents if e["name"].lower().startswith("create ") or e["name"].lower().startswith("run ") or "follow-up" in e["name"].lower() or "expected" in e["name"].lower()]
                
                conn.close()
                
                avg_node_degree = (total_rels / total_nodes) if total_nodes > 0 else 0.0
                
                print(f"\n📊 === KNOWLEDGE GRAPH QUALITY DASHBOARD ===")
                print(f"Total Nodes: {total_nodes}")
                print(f"Total Edges/Relations: {total_rels}")
                print(f"Average Node Degree: {avg_node_degree:.2f}")
                print(f"Projects Count: {project_count}")
                print(f"People Count: {people_count}")
                print(f"Technology Count: {tech_count}")
                print(f"\nDuplicate Resolution Candidates ({len(dup_candidates)}):")
                for c in dup_candidates:
                    print(c)
                print(f"\nPlaceholder Nodes Found ({len(placeholders_found)}):")
                for p in placeholders_found:
                    print(f"  • {p}")
                print(f"\nConversational Noise Nodes ({len(noise_found)}):")
                for n in noise_found:
                    print(f"  • {n}")
                print("="*50)
                continue

            # CLI Command: Timeline log
            if user_input.startswith("/timeline "):
                parts = user_input.split(" ")
                if len(parts) >= 3:
                    start_date = parts[1]
                    end_date = parts[2]
                    
                    conn = db_manager.get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT source_app, title, last_synced FROM workspace_cache WHERE last_synced BETWEEN ? AND ? ORDER BY last_synced ASC",
                        (start_date, end_date)
                    )
                    rows = cursor.fetchall()
                    conn.close()
                    
                    print(f"\n📅 === TIMELINE LOG: {start_date} to {end_date} ===")
                    for r in rows:
                        print(f"  - [{r['last_synced']}] [{r['source_app'].upper()}] {r['title']}")
                    print("="*40)
                else:
                    print("Usage: /timeline YYYY-MM-DD YYYY-MM-DD")
                continue

            # CLI Command: Relationship Explorer
            if user_input.startswith("/explore "):
                parts = user_input.split(" ")
                if len(parts) >= 3:
                    src = parts[1]
                    tgt = parts[2]
                    
                    src_node = graph_store.get_node(src)
                    tgt_node = graph_store.get_node(tgt)
                    
                    if not src_node or not tgt_node:
                        print("One or both entities not found in knowledge graph.")
                        continue
                        
                    rels_src = graph_store.get_multi_hop_relationships(src, depth=2)
                    path = []
                    for r in rels_src:
                        if (r["source"].lower() == src.lower() and r["target"].lower() == tgt.lower()) or \
                           (r["source"].lower() == tgt.lower() and r["target"].lower() == src.lower()):
                            path.append(r)
                        elif r["target"].lower() == tgt.lower() or r["source"].lower() == tgt.lower():
                            path.append(r)
                            
                    print(f"\n🔗 === RELATIONSHIP EXPLORATION: {src} ➔ {tgt} ===")
                    if path:
                        for p in path:
                            print(f"  - ({p['source']}) -- {p['relation_type']} --> ({p['target']})")
                    else:
                        print("No direct 1 or 2-hop paths found connecting entities.")
                    print("="*40)
                else:
                    print("Usage: /explore <entity1> <entity2>")
                continue

            # CLI Command: Render Graph
            if user_input.lower() == "/graph":
                nodes = graph_store.get_all_nodes()
                edges = graph_store.get_all_relationships()
                print("\n📊 --- KNOWLEDGE GRAPH STATUS --- 📊")
                print(f"Nodes ({len(nodes)}):")
                for n in nodes:
                    desc_str = f" ({n.description})" if n.description else ""
                    print(f"  • [{n.entity_type}] {n.name}{desc_str} (properties: {n.properties})")
                print(f"Edges ({len(edges)}):")
                for e in edges:
                    print(f"  • ({e['source']}) -- {e['relation_type']} --> ({e['target']})")
                print("=" * 40)
                continue
            
            # CLI Command: Debug retrieval diagnostics
            if user_input.startswith("/debug-retrieval "):
                parts = user_input.split(" ", 1)
                if len(parts) > 1 and parts[1].strip():
                    query = parts[1].strip()
                    fts_res = searcher.search_workspace_cache(query, limit=5)
                    vector_res = searcher.search_vector_store(query, limit=5)
                    graph_res = searcher.search_graph(query, limit=5)
                    
                    from retrieval.fusion import ReciprocalRankFusion
                    from retrieval.context import ContextBuilder
                    fusion = ReciprocalRankFusion()
                    fused = fusion.fuse(fts_res, vector_res)
                    context_builder = ContextBuilder(char_budget=10000)
                    context = context_builder.build_context(fused, graph_res)
                    
                    token_count = len(context) // 4
                    
                    print(f"\n🔍 === RETRIEVAL DIAGNOSTICS: '{query}' ===")
                    print(f"FTS Hits ({len(fts_res)}):")
                    for r in fts_res:
                        print(f"  - [{r['source_app'].upper()}] {r['title']}")
                    print(f"\nVector Hits ({len(vector_res)}):")
                    for r in vector_res:
                        display_name = r['payload'].get('title') or r['payload'].get('name') or "Unnamed"
                        print(f"  - {display_name} (score: {r['score']:.4f})")
                    print(f"\nGraph Hits (Entities: {len(graph_res.get('entities', []))}, Relationships: {len(graph_res.get('relationships', []))}):")
                    for ent in graph_res.get('entities', []):
                        print(f"  - {ent['name']} ({ent['entity_type']})")
                    for rel in graph_res.get('relationships', []):
                        print(f"  - ({rel['source']}) -- {rel['relation_type']} --> ({rel['target']})")
                    print(f"\nToken Count: {token_count}")
                    print(f"Context Size (chars): {len(context)}")
                    print("="*50)
                else:
                    print("Usage: /debug-retrieval <query>")
                continue

            # Send standard user query to LangGraph execution builder
            config = {"configurable": {"thread_id": thread_id}}
            inputs = {
                "messages": [("user", user_input)],
                "thread_id": thread_id
            }
            
            print("\nThinking...")
            with SqliteSaver.from_conn_string(db_path) as checkpointer:
                response = agent_graph.invoke(inputs, config=config)
                
            messages = response.get("messages", [])
            if messages:
                last_msg = messages[-1]
                print(f"\nMemory-OS:\n{last_msg.content}")
            else:
                print("\nMemory-OS: No response received.")
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memory-OS Engine Startup Option")
    parser.add_argument("--server", "-s", action="store_true", help="Start the FastAPI REST web server")
    args = parser.parse_args()

    if args.server:
        print("Starting FastAPI REST API server...")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        run_cli()
