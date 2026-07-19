"""
Command: memory-os init

Performs first-time setup and onboarding for Memory-OS using ComposeManager.
"""

import sys
import uuid
import os
from infrastructure.workspace import ensure_workspace, get_db_path
from infrastructure.config import generate_default_config, save_config, load_config
from infrastructure.compose import ComposeManager, wait_for_services
from infrastructure.health import run_all_checks, check_docker, check_neo4j, check_qdrant
from storage.db import init_db
from core.embedder import Embedder



def get_input(prompt: str, secret: bool = False, default: str = "") -> str:
    """Prompt the user for input with an optional default value."""
    import getpass
    suffix = f" [{default}]" if default else ""
    full_prompt = f"{prompt}{suffix}: "
    try:
        if secret:
            val = getpass.getpass(full_prompt)
        else:
            val = input(full_prompt)
        return val.strip() or default
    except (KeyboardInterrupt, EOFError):
        print("\nInitialization cancelled by user.")
        sys.exit(1)


def execute(args):
    """Run the init command wizard following the exact 11 steps."""
    print("==================================================")
    print("🧠 MEMORY-OS INITIALIZATION WIZARD")
    print("==================================================")

    # ── Step 1: Check Python ──────────────────────────────────
    print("\n[Step 1/11] Checking Python version...")
    python_ok = sys.version_info >= (3, 12)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if not python_ok:
        print(f"❌ Python version {py_ver} is not supported. Requires >= 3.12.")
        sys.exit(1)
    print(f"  ✓ Python version: {py_ver}")

    # ── Step 2: Check Docker daemon ──────────────────────────
    print("\n[Step 2/11] Checking Docker daemon...")
    docker_ok, docker_detail = check_docker()
    if not docker_ok:
        print("----------------------------------")
        print("Docker Desktop is not running.")
        print("")
        print("stderr:")
        print(docker_detail)
        print("")
        print("Start Docker Desktop and rerun:")
        print("memory-os init")
        print("----------------------------------")
        sys.exit(1)
    print("  ✓ Docker Daemon: Running")

    # ── Step 3: Create workspace ─────────────────────────────
    print("\n[Step 3/11] Creating workspace directories...")
    ensure_workspace("default")
    print("  ✓ Workspace path initialized at ~/.memory-os")

    # ── Step 4: Generate docker-compose.yml ──────────────────
    print("\n[Step 4/11] Generating docker-compose.yml...")
    from infrastructure.config import get_config
    existing_config = get_config()
    existing_password = existing_config.get("neo4j", {}).get("password") or "memory_neo"
    
    manager = ComposeManager()
    manager.generate_compose(profile="default", password=existing_password)
    print("  ✓ docker-compose.yml generated at ~/.memory-os/docker-compose.yml")

    # ── Step 5: Launch Neo4j + Qdrant ─────────────────────────
    print("\n[Step 5/11] Launching local services (Neo4j, Qdrant)...")
    docker_services_failed = False
    if not docker_ok:
        print("  ⚠️ Skipped: Docker is not available.")
        docker_services_failed = True
        neo4j_ok = False
        qdrant_ok = False
    else:
        neo4j_ok, _ = check_neo4j()
        qdrant_ok, _ = check_qdrant()
        if neo4j_ok and qdrant_ok:
            print("  ✓ Neo4j already running")
            print("  ✓ Qdrant already running")
        else:
            if not manager.up(profile="default"):
                print("  ⚠️ Warning: Failed to start docker compose services. Setup will continue using local SQLite storage.")
                docker_services_failed = True
            else:
                print("  ✓ Containers launched.")

    # ── Step 6: Wait until healthy ────────────────────────────
    print("\n[Step 6/11] Waiting for services to become healthy...")
    if docker_services_failed:
        print("  ⚠️ Skipped: Local services are not running.")
    elif neo4j_ok and qdrant_ok:
        print("  ✓ Services are healthy.")
    else:
        if not wait_for_services(timeout=60):
            print("  ⚠️ Warning: Services failed to respond to health checks in time. Setup will continue using local SQLite storage.")
        else:
            print("  ✓ Services are healthy.")

    # ── Step 7: Initialize SQLite ─────────────────────────────
    print("\n[Step 7/11] Initializing SQLite database...")
    os.environ["MEMORY_OS_DB_PATH"] = str(get_db_path("default"))
    init_db()
    print("  ✓ SQLite database schema initialized.")

    # ── Step 8: Configure API Keys ───────────────────────────
    print("\n[Step 8/11] Configuring API keys & settings...")
    neo4j_password = get_input("Set Neo4j database password", secret=True, default=existing_password)
    groq_api_key = get_input("Enter Groq API Key", secret=True, default=existing_config.get("groq", {}).get("api_key", ""))
    composio_api_key = get_input("Enter Composio API Key", secret=True, default=existing_config.get("composio", {}).get("api_key", ""))

    composio_user_id = existing_config.get("composio", {}).get("user_id") or str(uuid.uuid4())

    answers = {
        "neo4j_password": neo4j_password,
        "groq_api_key": groq_api_key,
        "composio_api_key": composio_api_key,
        "composio_user_id": composio_user_id
    }

    config_dict = generate_default_config(answers)
    save_config(config_dict)
    load_config()
    
    if neo4j_password != existing_password:
        manager.generate_compose(profile="default", password=neo4j_password)
        print("  ✓ docker-compose.yml updated with new password.")

    print("  ✓ Configuration saved to ~/.memory-os/config.toml")

    # ── Step 9: Authenticate Composio ────────────────────────
    print("\n[Step 9/11] Configuring integration connectors...")
    setup_connectors = get_input("Configure connectors (GitHub, Gmail, Notion) now? (Y/n)", default="y").lower()
    if setup_connectors == "y" and composio_api_key:
        try:
            from composio import Composio
            c = Composio(api_key=composio_api_key)
            session = c.create(user_id=composio_user_id)
            
            toolkits_to_connect = [
                ("github", "GitHub"),
                ("gmail", "Gmail"),
                ("notion", "Notion")
            ]
            
            for slug, name in toolkits_to_connect:
                connect_this = get_input(f"Connect to {name}? (Y/n)", default="y").lower()
                if connect_this == "y":
                    print(f"  Initiating OAuth for {name}...")
                    try:
                        req = session.authorize(slug)
                        print(f"  👉 Please open this URL in your browser to complete authentication:\n     {req.redirect_url}")
                        print("  Waiting up to 30 seconds for completion...")
                        try:
                            req.wait_for_connection(timeout=30)
                            print(f"  ✓ {name} connected successfully!")
                        except Exception:
                            print(f"  ⚠️ Connection verification timed out. You can connect it later or run 'memory-os doctor'.")
                    except Exception as err:
                        print(f"  ⚠️ Failed to initiate connection for {name}: {err}")
        except Exception as e:
            print(f"  ⚠️ Error setting up Composio session: {e}")
    else:
        print("  Skipped connectors configuration.")

    # ── Step 10: Warm embedding model ─────────────────────────
    print("\n[Step 10/11] Preparing embedding model...")
    warm_model = get_input("Download and cache embedding model (all-MiniLM-L6-v2) now? (Y/n)", default="y").lower()
    if warm_model == "y":
        print("  Downloading model (this may take a minute)...")
        try:
            embedder = Embedder()
            _ = embedder.model
            print("  ✓ Embedding model cached successfully.")
        except Exception as e:
            print(f"  ⚠️ Warning: Failed to cache model during setup: {e}")
            print("  Model will be downloaded automatically on the first query.")
    else:
        print("  Skipped model download.")

    # ── Step 11: Done ─────────────────────────────────────────
    print("\n[Step 11/11] Running initial health checks...")
    print("==================================================")
    print("🏥 RUNNING INITIAL HEALTH CHECKS")
    print("==================================================")
    checks = run_all_checks()
    for name, passed, detail in checks:
        icon = "✓" if passed else "✗"
        print(f"  {icon} {name}: {detail}")
    
    print("\n==================================================")
    print("🎉 MEMORY-OS INITIALIZED SUCCESSFULLY!")
    print("==================================================")
    print("You can now run: ")
    print("  memory-os sync    - to import your documents and emails")
    print("  memory-os ask     - to query your personal knowledge base")
    print("  memory-os         - to launch the interactive menu")
    print("==================================================")
