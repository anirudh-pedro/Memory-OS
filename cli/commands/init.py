"""
Command: memory-os init

Performs first-time setup and onboarding for Memory-OS.
Provisions the workspace directory structure, creates config.toml,
spins up Neo4j and Qdrant via docker compose, initializes SQLite,
pre-warms the embedding model, and launches Composio toolkit OAuth flows.
"""

import sys
import uuid
import time
import os
from pathlib import Path
from infrastructure.workspace import ensure_workspace, get_db_path
from infrastructure.config import generate_default_config, save_config, load_config
from infrastructure.docker import check_docker_installed, check_docker_compose_installed, check_docker_running
from infrastructure.compose import compose_up, wait_for_services
from infrastructure.health import run_all_checks
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
    """Run the init command."""
    print("==================================================")
    print("🧠 MEMORY-OS INITIALIZATION WIZARD")
    print("==================================================")

    # 1. System Dependency Checks
    print("\n[1/7] Checking system dependencies...")
    
    python_ok = sys.version_info >= (3, 12)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if not python_ok:
        print(f"❌ Python version {py_ver} is not supported. Requires >= 3.12.")
        sys.exit(1)
    print(f"  ✓ Python version: {py_ver}")

    docker_ok, docker_ver = check_docker_installed()
    if not docker_ok:
        print("❌ Docker is not installed or not in PATH.")
        sys.exit(1)
    print(f"  ✓ Docker: {docker_ver}")

    compose_ok, compose_ver = check_docker_compose_installed()
    if not compose_ok:
        print("❌ Docker Compose is not installed.")
        sys.exit(1)
    print(f"  ✓ Docker Compose: {compose_ver}")

    if not check_docker_running():
        print("❌ Docker daemon is not running. Please start Docker and retry.")
        sys.exit(1)
    print("  ✓ Docker Daemon: Running")

    # 2. Workspace Tree Setup
    print("\n[2/7] Creating workspace directories...")
    ensure_workspace("default")
    print("  ✓ Workspace path initialized at ~/.memory-os")

    # 3. Configure API Credentials & Settings
    print("\n[3/7] Configuring credentials...")
    neo4j_password = get_input("Set Neo4j database password", secret=True, default="memory_neo")
    groq_api_key = get_input("Enter Groq API Key", secret=True)
    composio_api_key = get_input("Enter Composio API Key", secret=True)

    # Generate auto Composio User UUID
    composio_user_id = str(uuid.uuid4())

    answers = {
        "neo4j_password": neo4j_password,
        "groq_api_key": groq_api_key,
        "composio_api_key": composio_api_key,
        "composio_user_id": composio_user_id
    }

    config_dict = generate_default_config(answers)
    save_config(config_dict)
    
    # Force reload config in current process memory
    load_config()
    
    # Overwrite MEMORY_OS_DB_PATH in environment dynamically to point to the workspace DB
    os.environ["MEMORY_OS_DB_PATH"] = str(get_db_path("default"))

    print("  ✓ Configuration saved to ~/.memory-os/config.toml")

    # 4. Service Provisioning via Docker Compose
    print("\n[4/7] Provisioning local services (Neo4j, Qdrant)...")
    if not compose_up():
        print("❌ Failed to start docker compose services.")
        sys.exit(1)
    print("  ✓ Containers launched. Waiting for services to become healthy...")
    
    if not wait_for_services(timeout=60):
        print("❌ Services failed to start or respond to health checks in time.")
        sys.exit(1)
    print("  ✓ Services are healthy.")

    # 5. Schema & Database Initialization
    print("\n[5/7] Initializing SQLite database...")
    init_db()
    print("  ✓ SQLite database schema initialized.")

    # 6. Optional Embedding Model Warming
    print("\n[6/7] Preparing embedding model...")
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

    # 7. Optional Composio Integration OAuth
    print("\n[7/7] Configuring integration connectors...")
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
                            # Wait for active connection
                            req.wait_for_connection(timeout=30000)
                            print(f"  ✓ {name} connected successfully!")
                        except Exception:
                            print(f"  ⚠️ Connection verification timed out. You can connect it later or run 'memory-os doctor'.")
                    except Exception as err:
                        print(f"  ⚠️ Failed to initiate connection for {name}: {err}")
        except Exception as e:
            print(f"  ⚠️ Error setting up Composio session: {e}")
    else:
        print("  Skipped connectors configuration.")

    # Verification Report
    print("\n==================================================")
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
