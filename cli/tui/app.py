import os
import sys
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Input, Static, Button, Label, ContentSwitcher
from textual.binding import Binding
from textual.reactive import reactive

from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel

# Existing CLI/core functionality imports
from infrastructure.workspace import get_active_profile, get_db_path
from infrastructure.config import load_config
from storage.db import (
    get_repo_count,
    get_email_count,
    get_repository_document_count,
    get_connection
)
from core.vector_store import get_vector_index_stats, run_semantic_search
from core.llm import run_hybrid_rag_stream
from infrastructure.health import (
    check_docker, check_neo4j, check_qdrant, check_sqlite, check_groq, check_composio, check_embedding_model, check_connector
)
from infrastructure.observability import parse_observability_metrics


class Sidebar(Static):
    """Collapsible sidebar containing workspace details, status indicators, and health checks."""

    active_profile_name = reactive("default")
    repo_count = reactive(0)
    doc_count = reactive(0)
    email_count = reactive(0)
    vector_count = reactive(0)

    # Health states
    docker_status = reactive("Checking...")
    qdrant_status = reactive("Checking...")
    neo4j_status = reactive("Checking...")
    groq_status = reactive("Checking...")

    # Connector states
    github_status = reactive("Checking...")
    gmail_status = reactive("Checking...")
    notion_status = reactive("Checking...")

    def on_mount(self) -> None:
        """Set up intervals to refresh information periodically."""
        self.update_stats()
        self.update_health()
        self.set_interval(5.0, self.update_stats)
        self.set_interval(10.0, self.update_health)

    def update_stats(self) -> None:
        """Retrieve count statistics from database and vector index."""
        try:
            self.active_profile_name = get_active_profile()
            self.repo_count = get_repo_count()
            self.doc_count = get_repository_document_count()
            self.email_count = get_email_count()
            self.vector_count = get_vector_index_stats().get("vectors", 0)
        except Exception:
            pass

    def update_health(self) -> None:
        """Execute non-blocking system checkups."""
        self.run_worker(self.perform_health_checks())

    async def perform_health_checks(self) -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=4)

        # Runs checkers in executor to prevent blocking Textual thread
        docker_ok, _ = await loop.run_in_executor(executor, check_docker)
        self.docker_status = "[green]ONLINE[/]" if docker_ok else "[red]OFFLINE[/]"

        qdrant_ok, _ = await loop.run_in_executor(executor, check_qdrant)
        self.qdrant_status = "[green]ONLINE[/]" if qdrant_ok else "[red]OFFLINE[/]"

        neo4j_ok, _ = await loop.run_in_executor(executor, check_neo4j)
        self.neo4j_status = "[green]ONLINE[/]" if neo4j_ok else "[red]OFFLINE[/]"

        groq_ok, _ = await loop.run_in_executor(executor, check_groq)
        self.groq_status = "[green]READY[/]" if groq_ok else "[red]NO KEY[/]"

        github_ok, _ = await loop.run_in_executor(executor, check_connector, "github")
        self.github_status = "[green]ACTIVE[/]" if github_ok else "[yellow]INACTIVE[/]"

        gmail_ok, _ = await loop.run_in_executor(executor, check_connector, "gmail")
        self.gmail_status = "[green]ACTIVE[/]" if gmail_ok else "[yellow]INACTIVE[/]"

        notion_ok, _ = await loop.run_in_executor(executor, check_connector, "notion")
        self.notion_status = "[green]ACTIVE[/]" if notion_ok else "[yellow]INACTIVE[/]"

    def watch_active_profile_name(self) -> None:
        self.refresh_ui()

    def watch_repo_count(self) -> None:
        self.refresh_ui()

    def watch_doc_count(self) -> None:
        self.refresh_ui()

    def watch_email_count(self) -> None:
        self.refresh_ui()

    def watch_vector_count(self) -> None:
        self.refresh_ui()

    def watch_docker_status(self) -> None:
        self.refresh_ui()

    def watch_qdrant_status(self) -> None:
        self.refresh_ui()

    def watch_neo4j_status(self) -> None:
        self.watch_neo4j_status_impl()

    def watch_neo4j_status_impl(self) -> None:
        self.refresh_ui()

    def watch_groq_status(self) -> None:
        self.refresh_ui()

    def watch_github_status(self) -> None:
        self.refresh_ui()

    def watch_gmail_status(self) -> None:
        self.refresh_ui()

    def watch_notion_status(self) -> None:
        self.refresh_ui()

    def refresh_ui(self) -> None:
        """Compose output markup."""
        content = (
            f"[bold cyan]📁 Workspace Info[/bold cyan]\n"
            f"Profile: [bold white]{self.active_profile_name}[/bold white]\n"
            f"Repos:   [cyan]{self.repo_count}[/cyan]\n"
            f"Docs:    [cyan]{self.doc_count}[/cyan]\n"
            f"Emails:  [cyan]{self.email_count}[/cyan]\n"
            f"Vectors: [cyan]{self.vector_count}[/cyan]\n\n"
            f"[bold cyan]⚡ Service Health[/bold cyan]\n"
            f"Docker:  {self.docker_status}\n"
            f"Qdrant:  {self.qdrant_status}\n"
            f"Neo4j:   {self.neo4j_status}\n"
            f"Groq API: {self.groq_status}\n\n"
            f"[bold cyan]🔌 Integrations[/bold cyan]\n"
            f"GitHub:  {self.github_status}\n"
            f"Gmail:   {self.gmail_status}\n"
            f"Notion:  {self.notion_status}\n\n"
            f"[bold cyan]⌨️ Shortcuts[/bold cyan]\n"
            f"[cyan]ctrl+1[/cyan]: Chat\n"
            f"[cyan]ctrl+2[/cyan]: Sync\n"
            f"[cyan]ctrl+3[/cyan]: Doctor\n"
            f"[cyan]ctrl+4[/cyan]: Graph\n"
            f"[cyan]ctrl+5[/cyan]: Search\n"
            f"[cyan]ctrl+6[/cyan]: Monitor\n"
            f"[cyan]ctrl+7[/cyan]: Settings\n"
            f"[cyan]ctrl+q[/cyan]: Quit"
        )
        self.update(Panel(content, title="Memory-OS", border_style="#1F2937"))


class ChatPanel(Container):
    """Main Chat Interface supporting streaming responses and input field."""

    def compose(self) -> ComposeResult:
        with Vertical(id="chat_container"):
            with VerticalScroll(id="chat_history_scroll"):
                welcome_md = (
                    "```\n"
                    " __  __                                     ____   ____\n"
                    "|  \\/  | ___ _ __ ___   ___  _ __ _   _    / ___| / ___|\n"
                    "| |\\/| |/ _ \\ '_ ` _ \\ / _ \\| '__| | | |   \\___ \\| |\n"
                    "| |  | |  __/ | | | | | (_) | |  | |_| |    ___) | |___\n"
                    "|_|  |_|\\___|_| |_| |_|\\___/|_|   \\__, |   |____/ \\____|\n"
                    "                                  |___/\n"
                    "```\n"
                    "**Grounded Personal Knowledge Operating System**\n\n"
                    "Ask questions grounded against your connected workspace: repositories, documentation files, and synced emails.\n\n"
                    "💡 *Tip: Try asking: 'tell me about my projects' or 'what repositories use Python?'*"
                )
                yield Static(
                    RichMarkdown(welcome_md),
                    id="welcome_message"
                )
            with Horizontal(id="input_bar"):
                yield Label("❯", id="prompt_symbol")
                yield Input(placeholder="Ask a question...", id="chat_input")

    def on_mount(self) -> None:
        self.query_one("#chat_input").focus()

    def scroll_to_bottom(self) -> None:
        self.query_one("#chat_history_scroll").scroll_end(animate=False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self.process_message()

    async def process_message(self) -> None:
        chat_input = self.query_one("#chat_input", Input)
        user_text = chat_input.value.strip()
        if not user_text:
            return

        chat_input.value = ""

        # Remove welcome message on first interaction
        try:
            self.query_one("#welcome_message").remove()
        except Exception:
            pass

        # Append User Message
        history_scroll = self.query_one("#chat_history_scroll")
        user_markup = f"[bold green]● You[/bold green]\n\n{user_text}"
        history_scroll.mount(
            Static(user_markup, classes="chat_msg_user")
        )

        # Append Assistant Loading/Streaming Message
        agent_msg = Static("[bold cyan]● Memory-OS[/bold cyan]\n\n[italic dim]Thinking...[/italic dim]", classes="chat_msg_agent")
        history_scroll.mount(agent_msg)
        self.scroll_to_bottom()

        # Disable input while processing
        chat_input.disabled = True

        # Run generator task in a background worker
        self.run_worker(self.stream_response(user_text, agent_msg))

    async def stream_response(self, question: str, response_widget: Static) -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        def get_generator():
            return run_hybrid_rag_stream(question)

        try:
            gen = await loop.run_in_executor(executor, get_generator)
        except Exception as e:
            response_widget.update(f"[bold red]● Error[/bold red]\n\n{e}")
            self.enable_input()
            return

        answer_text = ""
        sources = []
        repos = []
        query_class = "Unknown"

        sentinel = object()
        while True:
            try:
                item = await loop.run_in_executor(executor, next, gen, sentinel)
                if item is sentinel:
                    break
            except Exception as e:
                response_widget.update(f"[bold red]● Error[/bold red]\n\n{e}")
                break

            if item["type"] == "diagnostics":
                query_class = item["data"].get("query_class", "Unknown")
            elif item["type"] == "token":
                answer_text += item["content"]
                response_widget.update(f"[bold cyan]● Memory-OS ({query_class})[/bold cyan]\n\n{answer_text}")
                self.scroll_to_bottom()
            elif item["type"] == "done":
                sources = item["sources"]
                repos = item["repositories"]
                confidence = item["confidence"]

                # Build final polished response with markdown formatting
                final_md = answer_text
                if confidence > 0.0:
                    metadata = []
                    if sources:
                        metadata.append(f"**Sources**: {', '.join(sources)}")
                    if repos:
                        metadata.append(f"**Repositories**: {', '.join(repos)}")
                    metadata.append(f"**Confidence**: {confidence:.1f}")
                    final_md += "\n\n---\n" + "\n".join(metadata)

                response_widget.update(RichMarkdown(f"### ● Memory-OS ({query_class})\n\n{final_md}"))
                self.scroll_to_bottom()

        self.enable_input()

    def enable_input(self) -> None:
        chat_input = self.query_one("#chat_input", Input)
        chat_input.disabled = False
        chat_input.focus()
        self.scroll_to_bottom()


class DoctorPanel(Container):
    """System diagnostic view execution wizard."""

    def compose(self) -> ComposeResult:
        with Vertical(id="doctor_panel"):
            yield Label("[bold cyan]Memory-OS Doctor Panel[/bold cyan]", id="doctor_title")
            yield Label("Run dynamic health checkups on workspace services (Docker, SQLite, Qdrant, Neo4j, LLM key verification).")
            yield Button("Run Diagnostics", id="run_doctor_btn", variant="primary")
            with VerticalScroll(id="doctor_results_scroll"):
                yield Static("Click 'Run Diagnostics' to run tests.", id="doctor_results")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run_doctor_btn":
            results_static = self.query_one("#doctor_results", Static)
            results_static.update("Running checkups... please wait...")
            event.button.disabled = True
            self.run_worker(self.execute_diagnostics())

    async def execute_diagnostics(self) -> None:
        btn = self.query_one("#run_doctor_btn", Button)
        results_static = self.query_one("#doctor_results", Static)
        
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=4)

        report = []
        
        def run_all():
            checks = {
                "Python": check_python,
                "Docker Daemon": check_docker,
                "SQLite DB": check_sqlite,
                "Qdrant DB": check_qdrant,
                "Neo4j Graph": check_neo4j,
                "Groq LLM": check_groq,
                "Composio API": check_composio,
                "Embedding Cache": check_embedding_model,
            }
            res = {}
            for name, func in checks.items():
                try:
                    res[name] = func()
                except Exception as e:
                    res[name] = (False, f"Crash: {e}")
            return res

        results = await loop.run_in_executor(executor, run_all)

        report.append("🔍 [bold cyan]System Diagnostics Report[/bold cyan]")
        report.append("=" * 45)
        
        healthy_count = 0
        for name, (ok, desc) in results.items():
            icon = "[green]✓ Healthy[/green]" if ok else "[red]❌ Unhealthy[/red]"
            report.append(f"{name:<20} : {icon:<12} ({desc})")
            if ok:
                healthy_count += 1
                
        report.append("=" * 45)
        report.append(f"Summary: [bold]{healthy_count}/{len(results)}[/bold] services are functional.")

        results_static.update(Panel("\n".join(report), border_style="#1F2937"))
        btn.disabled = False


class SyncPanel(Container):
    """Workspace synchronization action board."""

    def compose(self) -> ComposeResult:
        with Vertical(id="sync_panel"):
            yield Label("[bold cyan]Synchronization Panel[/bold cyan]")
            yield Label("Sync repositories, chunk documentation files, build vector embeddings and sync Neo4j.")
            with Horizontal():
                yield Button("Sync All Sources", id="sync_all_btn", variant="primary")
                yield Button("Rebuild Index", id="sync_rebuild_btn", variant="error")
            with VerticalScroll(id="sync_results_scroll"):
                yield Static("Click a sync button to start synchronizing.", id="sync_log_output")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        log_widget = self.query_one("#sync_log_output", Static)
        btn_all = self.query_one("#sync_all_btn", Button)
        btn_rebuild = self.query_one("#sync_rebuild_btn", Button)

        btn_all.disabled = True
        btn_rebuild.disabled = True

        rebuild = (event.button.id == "sync_rebuild_btn")
        log_widget.update("Starting sync... please wait...")

        self.run_worker(self.execute_sync(rebuild, btn_all, btn_rebuild, log_widget))

    async def execute_sync(self, rebuild: bool, btn_all: Button, btn_rebuild: Button, log_widget: Static) -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        import sys
        from io import StringIO

        def run_sync_redirected():
            # Redirect stdout to capture progress messages from sync pipeline
            old_stdout = sys.stdout
            sys.stdout = mystdout = StringIO()
            
            try:
                # Import handlers
                from connectors.registry import get_connector
                from core.vector_store import run_reindexing
                from storage.graph import GraphStore

                print("Step 1: Authenticating and connecting GitHub...")
                github = get_connector("github")
                if github and github.authenticate():
                    github.sync()
                else:
                    print("GitHub sync skipped (not authenticated).")

                print("\nStep 2: Authenticating and connecting Gmail...")
                gmail = get_connector("gmail")
                if gmail and gmail.authenticate():
                    gmail.sync()
                else:
                    print("Gmail sync skipped (not authenticated).")

                print("\nStep 3: Authenticating and connecting Notion...")
                notion = get_connector("notion")
                if notion and notion.authenticate():
                    notion.sync()
                else:
                    print("Notion sync skipped (not authenticated).")

                print("\nStep 4: Running chunking and Qdrant reindexing...")
                # Run reindexing
                run_reindexing(repo_names=None)

                print("\nStep 5: Updating Neo4j Knowledge Graph...")
                try:
                    graph = GraphStore()
                    if graph.check_connectivity():
                        print("Neo4j database connected. Synchronizing node relations...")
                        from storage.db import get_connection
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT repo_name, language, url FROM repositories")
                        for r in cursor.fetchall():
                            graph.create_repository_node(r[0], r[1], r[2])
                        conn.close()
                        print("Neo4j node sync completed.")
                    else:
                        print("Neo4j offline. Skipped graph sync (falling back to SQLite).")
                except Exception as ex:
                    print(f"Graph update encountered error: {ex}")

                print("\nSync completed successfully!")
            except Exception as e:
                print(f"\nError during sync: {e}")
            finally:
                sys.stdout = old_stdout
            return mystdout.getvalue()

        output = await loop.run_in_executor(executor, run_sync_redirected)
        log_widget.update(Panel(output, title="Sync Log Output", border_style="#1F2937"))

        btn_all.disabled = False
        btn_rebuild.disabled = False


class GraphPanel(Container):
    """View graph metrics and technological detections."""

    def compose(self) -> ComposeResult:
        with Vertical(id="graph_panel"):
            yield Label("[bold cyan]Knowledge Graph Panel[/bold cyan]")
            yield Static("Loading graph statistics...", id="graph_stats")

    def on_mount(self) -> None:
        self.update_stats()
        self.set_interval(10.0, self.update_stats)

    def update_stats(self) -> None:
        self.run_worker(self.fetch_graph_stats())

    async def fetch_graph_stats(self) -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        def query_stats():
            conn = get_connection()
            cursor = conn.cursor()
            
            # Nodes count in SQLite (fallback graph)
            cursor.execute("SELECT COUNT(*) FROM graph_nodes")
            sq_nodes = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM graph_relationships")
            sq_rels = cursor.fetchone()[0]
            
            # Repo tech detection stats
            cursor.execute("SELECT repo_name, language FROM repositories LIMIT 10")
            repos = cursor.fetchall()
            
            conn.close()
            return sq_nodes, sq_rels, repos

        sq_nodes, sq_rels, repos = await loop.run_in_executor(executor, query_stats)

        # Check Neo4j stats
        neo_nodes, neo_rels = 0, 0
        neo_ok, _ = check_neo4j()
        if neo_ok:
            def query_neo():
                from neo4j import GraphDatabase
                uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
                user = os.getenv("NEO4J_USER", "neo4j")
                password = os.getenv("NEO4J_PASSWORD", "password")
                driver = GraphDatabase.driver(uri, auth=(user, password))
                with driver.session() as session:
                    n_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                    r_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
                driver.close()
                return n_count, r_count
            try:
                neo_nodes, neo_rels = await loop.run_in_executor(executor, query_neo)
            except Exception:
                pass

        stats_text = (
            f"[bold green]Connected Graph Storage Status[/bold green]\n\n"
            f"⚡ [bold cyan]Neo4j DB[/bold cyan]:   {'[green]ONLINE[/]' if neo_ok else '[red]OFFLINE[/]'}\n"
            f"   Nodes count:    {neo_nodes}\n"
            f"   Relations count: {neo_rels}\n\n"
            f"📁 [bold cyan]SQLite Graph (Fallback)[/bold cyan]\n"
            f"   Nodes count:    {sq_nodes}\n"
            f"   Relations count: {sq_rels}\n\n"
            f"[bold cyan]🔍 Repository Languages Detected[/bold cyan]\n"
        )
        for r_name, lang in repos:
            stats_text += f" - [white]{r_name}[/white] : {lang or 'Unknown'}\n"

        self.query_one("#graph_stats", Static).update(Panel(stats_text, border_style="#1F2937"))


class SearchPanel(Container):
    """Semantic Finder View."""

    def compose(self) -> ComposeResult:
        with Vertical(id="search_panel"):
            yield Label("[bold cyan]Vector Search Finder[/bold cyan]")
            yield Label("Input search phrase to perform raw vector queries on Qdrant.")
            with Horizontal(id="search_bar"):
                yield Input(placeholder="Search documents or chunks...", id="search_query_input")
                yield Button("Search", id="search_run_btn", variant="primary")
            with VerticalScroll(id="search_results_scroll"):
                yield Static("Results will appear here.", id="search_results")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self.execute_search()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search_run_btn":
            await self.execute_search()

    async def execute_search(self) -> None:
        query_input = self.query_one("#search_query_input", Input)
        query = query_input.value.strip()
        if not query:
            return

        results_static = self.query_one("#search_results", Static)
        results_static.update("Searching vectors... please wait...")

        self.run_worker(self.perform_vector_search(query, results_static))

    async def perform_vector_search(self, query: str, results_static: Static) -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        def run_search():
            return run_semantic_search(query, limit=10)

        try:
            results = await loop.run_in_executor(executor, run_search)
        except Exception as e:
            results_static.update(f"Error executing vector search: {e}")
            return

        if not results:
            results_static.update("No matching document chunks found in Qdrant.")
            return

        report = [f"Found {len(results)} matches for: '{query}'\n"]
        for idx, item in enumerate(results):
            score = item.get("score", 0.0)
            payload = item.get("payload", {})
            repo = payload.get("repository_name", "N/A")
            doc = payload.get("document_name", "N/A")
            idx_num = payload.get("chunk_index", 0)
            text = payload.get("chunk_text", "")
            
            report.append(f"[bold cyan]Match #{idx+1} (Score: {score:.3f})[/bold cyan]")
            report.append(f"Repo: [white]{repo}[/white] | Doc: [white]{doc}[/white] (Chunk {idx_num})")
            report.append(f"Snippet:\n[dim]{text[:300]}...[/dim]")
            report.append("-" * 45)

        results_static.update("\n".join(report))


class MonitorPanel(Container):
    """Latency dashboard displaying performance parser metrics."""

    def compose(self) -> ComposeResult:
        with Vertical(id="monitor_panel"):
            yield Label("[bold cyan]Observability Monitor[/bold cyan]")
            yield Static("Loading performance metrics from logs...", id="monitor_stats")

    def on_mount(self) -> None:
        self.update_stats()
        self.set_interval(10.0, self.update_stats)

    def update_stats(self) -> None:
        self.run_worker(self.fetch_monitor_stats())

    async def fetch_monitor_stats(self) -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        metrics = await loop.run_in_executor(executor, parse_observability_metrics)

        def avg(lst):
            return sum(lst) / len(lst) if lst else 0.0

        r_times = metrics.get("rag_times", [])
        l_times = metrics.get("llm_calls", [])
        v_uploads = metrics.get("qdrant_uploads", [])
        e_times = metrics.get("embedding_times", [])

        stats_text = (
            f"[bold green]System Latency Dashboard[/bold green]\n\n"
            f" - [bold cyan]Average RAG Pipeline[/bold cyan] : {avg(r_times):.2f}s ({len(r_times)} queries)\n"
            f" - [bold cyan]Average LLM generation[/bold cyan]: {avg(l_times):.2f}s ({len(l_times)} calls)\n"
            f" - [bold cyan]Average Embedding Gen[/bold cyan] : {avg([x[0] for x in e_times]):.2f}s ({len(e_times)} runs)\n"
            f" - [bold cyan]Average Qdrant Upload[/bold cyan] : {avg([x[0] for x in v_uploads]):.2f}s ({len(v_uploads)} runs)\n\n"
            f"[bold cyan] Recent Log Details[/bold cyan]\n"
        )
        if r_times:
            stats_text += f" - Last RAG execution: {r_times[-1]:.2f}s\n"
        if l_times:
            stats_text += f" - Last Groq response: {l_times[-1]:.2f}s\n"
        
        self.query_one("#monitor_stats", Static).update(Panel(stats_text, border_style="#1F2937"))


class SettingsPanel(Container):
    """View active configs and workspaces."""

    def compose(self) -> ComposeResult:
        with Vertical(id="settings_panel"):
            yield Label("[bold cyan]Memory-OS Configurations[/bold cyan]")
            yield Static("Loading workspace settings...", id="settings_details")

    def on_mount(self) -> None:
        self.update_settings()

    def update_settings(self) -> None:
        cfg = load_config()
        active = get_active_profile()
        db_path = get_db_path(active)

        details = (
            f"📁 [bold cyan]Active Config Settings[/bold cyan]\n\n"
            f"Active profile:  [bold white]{active}[/bold white]\n"
            f"SQLite DB Path:  {db_path}\n"
            f"Qdrant URL:      {cfg.get('qdrant', {}).get('url', 'http://localhost:6333')}\n"
            f"Neo4j Bolt URI:  {cfg.get('neo4j', {}).get('uri', 'bolt://localhost:7687')}\n"
            f"Groq Model:      {cfg.get('groq', {}).get('model', 'llama-3.3-70b-versatile')}\n"
            f"Embedding Model: {cfg.get('embeddings', {}).get('model', 'all-MiniLM-L6-v2')}\n"
        )
        self.query_one("#settings_details", Static).update(Panel(details, border_style="#1F2937"))


class MemoryOSTUIApp(App):
    """Main Textual full-screen terminal UI application."""

    TITLE = "Memory-OS Terminal UI"
    CSS = """
    Screen {
        background: #0B0F19;
    }
    
    #main_layout {
        height: 1fr;
    }

    Sidebar {
        width: 35;
        height: 100%;
        background: #111622;
        border-right: solid #1F2937;
    }

    ContentSwitcher {
        height: 100%;
        width: 1fr;
        padding: 1 2;
    }

    #chat_container {
        height: 100%;
    }

    #chat_history_scroll {
        height: 1fr;
        border: solid #1F2937;
        margin-bottom: 1;
        padding: 1 2;
        background: #0B0F19;
    }

    .chat_msg_user {
        margin: 1 0;
        background: #161B22;
        border-left: solid #10B981;
        padding: 1 2;
    }

    .chat_msg_agent {
        margin: 1 0;
        background: #111622;
        border-left: solid #3B82F6;
        padding: 1 2;
    }

    #input_bar {
        height: auto;
        margin-top: 1;
    }

    #chat_input {
        width: 1fr;
        background: #161B22;
        border: solid #1F2937;
        color: white;
    }

    #chat_send_btn {
        width: 12;
        margin-left: 1;
        background: #1F2937;
        color: white;
        border: none;
    }

    #chat_send_btn:hover {
        background: #3B82F6;
    }

    #search_bar {
        height: auto;
        margin-bottom: 1;
    }

    #search_query_input {
        width: 1fr;
        background: #161B22;
        border: solid #1F2937;
        color: white;
    }

    #search_run_btn {
        width: 12;
        margin-left: 1;
        background: #1F2937;
        color: white;
        border: none;
    }

    #search_run_btn:hover {
        background: #3B82F6;
    }

    #doctor_results_scroll, #sync_results_scroll, #search_results_scroll {
        height: 1fr;
        border: solid #1F2937;
        margin-top: 1;
        padding: 1 2;
        background: #0B0F19;
    }

    Button {
        min-width: 15;
        background: #1F2937;
        color: white;
        border: none;
    }

    Button:hover {
        background: #3B82F6;
    }

    Label {
        margin: 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "Sidebar"),
        Binding("ctrl+1", "switch_view('chat')", "Chat"),
        Binding("ctrl+2", "switch_view('sync')", "Sync"),
        Binding("ctrl+3", "switch_view('doctor')", "Doctor"),
        Binding("ctrl+4", "switch_view('graph')", "Graph"),
        Binding("ctrl+5", "switch_view('search')", "Search"),
        Binding("ctrl+6", "switch_view('monitor')", "Monitor"),
        Binding("ctrl+7", "switch_view('settings')", "Settings"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    sidebar_visible = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main_layout"):
            sidebar = Sidebar(id="sidebar_menu")
            sidebar.display = self.sidebar_visible
            yield sidebar
            with ContentSwitcher(initial="chat", id="panel_switcher"):
                yield ChatPanel(id="chat")
                yield SyncPanel(id="sync")
                yield DoctorPanel(id="doctor")
                yield GraphPanel(id="graph")
                yield SearchPanel(id="search")
                yield MonitorPanel(id="monitor")
                yield SettingsPanel(id="settings")
        yield Footer()

    def action_toggle_sidebar(self) -> None:
        """Collapse or show the sidebar."""
        self.sidebar_visible = not self.sidebar_visible
        sidebar = self.query_one("#sidebar_menu")
        sidebar.display = self.sidebar_visible

    def action_switch_view(self, panel_id: str) -> None:
        """Switch the main ContentSwitcher view."""
        switcher = self.query_one("#panel_switcher", ContentSwitcher)
        switcher.current = panel_id
        
        # Auto-focus search input if search panel is selected
        if panel_id == "search":
            try:
                self.query_one("#search_query_input").focus()
            except Exception:
                pass
        elif panel_id == "chat":
            try:
                self.query_one("#chat_input").focus()
            except Exception:
                pass


def check_python() -> tuple[bool, str]:
    """Check Python version (TUI internal wrapper)."""
    import sys
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 12)
    return ok, version


if __name__ == "__main__":
    app = MemoryOSTUIApp()
    app.run()
