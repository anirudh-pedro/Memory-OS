import os
import sys
import argparse
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn

# Repositories & Engine Imports
from memory.graph_manager import SQLiteGraphManager, Neo4jGraphManager
from memory.memory_manager import MessageRepository, WorkspaceCacheRepository
from memory.retrieval_engine import RetrievalEngine
from agents.personal_agent import MemoryAgentBuilder
from api.routes import create_router

# Composio & LangChain Imports
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

# 1. Global Setup & Database Configuration
db_path = "memory.db"
message_repo = MessageRepository(db_path)
cache_repo = WorkspaceCacheRepository(db_path)

# Dynamic DB Auto-switching based on environment variables
neo4j_uri = os.getenv("NEO4J_URI")
if neo4j_uri:
    logger.info("Connecting to Neo4j Graph Database...")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    graph_manager = Neo4jGraphManager(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
else:
    logger.info("Connecting to local SQLite Graph Manager...")
    graph_manager = SQLiteGraphManager(db_path)

# Initialize optional local Qdrant Client in-memory
qdrant_client = None
try:
    from qdrant_client import QdrantClient
    qdrant_client = QdrantClient(location=":memory:")
    logger.info("Local in-memory Qdrant client initialized.")
except Exception as e:
    logger.warning(f"Could not load QdrantClient: {e}. Semantic vector search disabled.")

retrieval_engine = RetrievalEngine(db_path, graph_manager, qdrant_client)

# 2. LLM Setup
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.getenv("GROQ_API_KEY")
)

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
        if t.args_schema is None:
            continue
        patched_fields = {}
        for name, field in t.args_schema.model_fields.items():
            annotation = field.annotation
            default = field.default
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
    agent_builder = MemoryAgentBuilder(
        llm=llm,
        tools=tools,
        message_repo=message_repo,
        graph_manager=graph_manager,
        retrieval_engine=retrieval_engine
    )
    agent_graph = agent_builder.build_graph()

# 5. FastAPI Instance setup
app = FastAPI(title="Memory-OS API", description="Production-grade Personal AI Memory OS backend.")
router = create_router(
    agent_graph=agent_graph,
    session=session,
    db_path=db_path,
    message_repo=message_repo,
    cache_repo=cache_repo,
    graph_manager=graph_manager,
    retrieval_engine=retrieval_engine
)
app.include_router(router)


# 6. Connection Validation
def ensure_connections():
    """Verify active toolkit logins. Blocks for browser authorization requests if connection is missing."""
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
    print("\n" + "="*45)
    print("🧠 MEMORY-OS INTERACTIVE CLI CHAT 🧠")
    print(f"Active Session ID: {thread_id}")
    print("="*45)
    print("Commands:")
    print("  /clear          - Clear current session chat history")
    print("  /session <id>   - Switch to/create a different session")
    print("  /graph          - Render current Knowledge Graph nodes and edges")
    print("  exit / quit     - Exit the chat")
    print("="*45)

    while True:
        try:
            user_input = input(f"\n[{thread_id}] You: ").strip()
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            # Command: Clear chat history
            if user_input.lower() == "/clear":
                import sqlite3
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
                cursor.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                conn.commit()
                conn.close()
                message_repo.clear_thread(thread_id)
                print(f"Memory cleared for session '{thread_id}'.")
                continue
            
            # Command: Switch session
            if user_input.startswith("/session "):
                parts = user_input.split(" ", 1)
                if len(parts) > 1 and parts[1].strip():
                    thread_id = parts[1].strip()
                    print(f"Switched to session '{thread_id}'.")
                else:
                    print("Invalid session ID.")
                continue

            # Command: Render Graph
            if user_input.lower() == "/graph":
                nodes = graph_manager.get_all_nodes()
                edges = graph_manager.get_all_relationships()
                print("\n📊 --- KNOWLEDGE GRAPH STATUS --- 📊")
                print(f"Nodes ({len(nodes)}):")
                for n in nodes:
                    print(f"  • [{n['entity_type']}] {n['name']} (properties: {n['properties']})")
                print(f"Edges ({len(edges)}):")
                for e in edges:
                    print(f"  • ({e['source']}) -- {e['relation_type']} --> ({e['target']})")
                print("=" * 40)
                continue
            
            config = {"configurable": {"thread_id": thread_id}}
            inputs = {
                "messages": [("user", user_input)],
                "thread_id": thread_id
            }
            
            print("\nThinking...")
            # We run in a context manager checkpoint session
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
