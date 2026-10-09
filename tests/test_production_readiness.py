"""
Production-Readiness Regression & Verification Test Suite.

Validates all 11 critical and functional remediations:
1. Path traversal / Zip Slip prevention in memory-os import
2. COMPOSIO_USER_ID and EMBEDDING_MODEL environment variable export
3. memory-os config reset subparser and execution
4. memory-os logs --tail 0 line count handling
5. Strict non-zero exit codes on command failures (migrate, update, config, workspace)
6. Graceful degradation in run_reindexing when Qdrant is unreachable
7. SQLite WAL mode, 30s busy timeout, and index migrations
8. Secret sanitization in memory-os export archives and config show
9. End-to-end clean user lifecycle simulation
"""

import os
import sys
import json
import zipfile
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add workspace root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.parser import build_parser
from cli.commands.import_cmd import execute as execute_import
from cli.commands.export import execute as execute_export
from cli.commands.config_cmd import execute as execute_config
from cli.commands.workspace import execute as execute_workspace
from cli.commands.migrate import execute as execute_migrate
from cli.commands.update import execute as execute_update
from cli.commands.logs import execute as execute_logs
from infrastructure.config import load_config, get_config, save_config, DEFAULTS
from storage.db import get_connection, init_db, CURRENT_SCHEMA_VERSION
from core.vector_store import run_reindexing
from core.embedder import Embedder


class DummyArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ── 1. Security: Zip Slip Path Traversal Prevention ─────────────

def test_import_zip_slip_prevention(tmp_path, capsys):
    """Verify that an archive with path traversal ('../') cannot write outside workspace."""
    workspace_dir = tmp_path / "workspace_target"
    workspace_dir.mkdir()
    qdrant_dir = workspace_dir / "qdrant"
    qdrant_dir.mkdir()
    neo4j_dir = workspace_dir / "neo4j"
    neo4j_dir.mkdir()

    outside_canary = tmp_path / "escaped_canary.txt"

    # Create a malicious zip file with path traversal
    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("metadata.json", json.dumps({"version": "1.0", "embedding_model": "all-MiniLM-L6-v2"}))
        zf.writestr("qdrant/../../escaped_canary.txt", "MALICIOUS PAYLOAD")
        zf.writestr("qdrant/valid_index.bin", "SAFE DATA")

    args = DummyArgs(file=str(evil_zip))

    with patch("cli.commands.import_cmd.get_active_profile", return_value="default"), \
         patch("cli.commands.import_cmd.get_profile_path", return_value=workspace_dir), \
         patch("cli.commands.import_cmd.get_db_path", return_value=workspace_dir / "workspace.db"), \
         patch("cli.commands.import_cmd.get_qdrant_path", return_value=qdrant_dir), \
         patch("cli.commands.import_cmd.get_neo4j_path", return_value=neo4j_dir), \
         patch("cli.commands.import_cmd._get_config_path", return_value=workspace_dir / "config.toml"), \
         patch("cli.commands.import_cmd.compose_stop"), \
         patch("cli.commands.import_cmd.compose_up", return_value=True), \
         patch("cli.commands.import_cmd.wait_for_services", return_value=True), \
         patch("builtins.input", return_value="y"):
        
        execute_import(args)

    # Assert canary file was NEVER created outside target
    assert not outside_canary.exists(), "CRITICAL: Malicious file escaped workspace directory!"
    # Assert valid file was safely unpacked
    assert (qdrant_dir / "valid_index.bin").exists()
    assert (qdrant_dir / "valid_index.bin").read_text() == "SAFE DATA"
    captured = capsys.readouterr()
    assert "path traversal detected" in captured.out


# ── 2. Functional: COMPOSIO_USER_ID and EMBEDDING_MODEL Export ─

def test_composio_user_id_and_embedding_export(tmp_path):
    """Verify that composio.user_id and embeddings.model in config are exported to os.environ."""
    test_user_id = "test-user-uuid-12345"
    test_model = "test-custom-embedding-model"

    env_overrides = {
        "MEMORY_OS_WORKSPACE": str(tmp_path),
        "COMPOSIO_USER_ID": "",
        "EMBEDDING_MODEL": "",
    }
    # Clean up env
    os.environ.pop("COMPOSIO_USER_ID", None)
    os.environ.pop("EMBEDDING_MODEL", None)

    cfg = dict(DEFAULTS)
    cfg["composio"] = {"api_key": "test_ak", "user_id": test_user_id}
    cfg["embeddings"] = {"model": test_model}

    with patch.dict(os.environ, env_overrides):
        with patch("infrastructure.config._get_config_path", return_value=tmp_path / "config.toml"):
            save_config(cfg)
            load_config()

            assert os.environ.get("COMPOSIO_USER_ID") == test_user_id
            assert os.environ.get("EMBEDDING_MODEL") == test_model

            embedder = Embedder()
            assert embedder.model_name == test_model


# ── 3. CLI: memory-os config reset Subcommand ──────────────────

def test_config_reset_subcommand(tmp_path):
    """Verify that config reset is parsed by CLI parser and resets config to DEFAULTS."""
    parser = build_parser()
    parsed = parser.parse_args(["config", "reset"])
    assert parsed.command == "config"
    assert parsed.config_action == "reset"

    with patch("builtins.input", return_value="y"), \
         patch("infrastructure.config._get_config_path", return_value=tmp_path / "config.toml"):
        execute_config(parsed)
        # Config should be saved with DEFAULTS
        loaded = get_config()
        assert loaded.get("active_profile") == "default"


# ── 4. CLI: memory-os logs --tail 0 ────────────────────────────

def test_logs_tail_zero(tmp_path, capsys):
    """Verify memory-os logs --tail 0 outputs 0 log lines instead of the full file."""
    log_file = tmp_path / "memory_os.log"
    log_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n", encoding="utf-8")

    args = DummyArgs(tail=0)
    with patch("cli.commands.logs.get_logs_path", return_value=tmp_path):
        execute_logs(args)

    captured = capsys.readouterr()
    assert "Last 0 lines" in captured.out
    assert "line 1" not in captured.out
    assert "line 5" not in captured.out


# ── 5. CLI: Failure Exit Codes ─────────────────────────────────

def test_migrate_failure_exit_code():
    """Verify migrate exits with 1 when migration fails."""
    with patch("cli.commands.migrate.init_db", side_effect=sqlite3.OperationalError("disk I/O error")):
        with pytest.raises(SystemExit) as exc:
            execute_migrate(DummyArgs())
        assert exc.value.code == 1


def test_update_failure_exit_code():
    """Verify update exits with 1 when docker pull fails."""
    fake_proc = MagicMock(returncode=1, stderr="Network timeout pulling images")
    with patch("infrastructure.compose.ComposeManager._run_cmd", return_value=fake_proc):
        with pytest.raises(SystemExit) as exc:
            execute_update(DummyArgs())
        assert exc.value.code == 1


def test_config_empty_action_exit_code():
    """Verify config exits with 1 when no action is provided."""
    with pytest.raises(SystemExit) as exc:
        execute_config(DummyArgs(config_action=None))
    assert exc.value.code == 1


def test_workspace_empty_action_exit_code():
    """Verify workspace exits with 1 when no action is provided."""
    with pytest.raises(SystemExit) as exc:
        execute_workspace(DummyArgs(workspace_action=None))
    assert exc.value.code == 1


# ── 6. Reliability: Qdrant Outage Graceful Degradation ──────────

def test_reindexing_qdrant_outage_does_not_crash():
    """Verify run_reindexing handles unreachable Qdrant without crashing sync."""
    with patch("core.vector_store.get_qdrant_client", side_effect=Exception("Connection refused to Qdrant")):
        res = run_reindexing(repo_names=["non_existent_repo"])
        assert isinstance(res, dict)
        assert res["vectors_uploaded"] == 0


# ── 7. Database: WAL Mode, Busy Timeout, and Indexes ────────────

def test_sqlite_wal_mode_and_concurrency(tmp_path):
    """Verify SQLite connection enables WAL mode, 30s timeout, and migration 2 indexes."""
    db_file = tmp_path / "concurrency_test.db"
    conn = get_connection(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal", f"Expected WAL mode, got {mode}"

        cursor.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 30000, f"Expected 30000ms busy timeout, got {timeout}"

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_emails_received_at'")
        assert cursor.fetchone() is not None, "Missing idx_emails_received_at index"

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_repo_docs_composite'")
        assert cursor.fetchone() is not None, "Missing idx_repo_docs_composite index"

        cursor.execute("SELECT MAX(version) FROM schema_versions")
        ver = cursor.fetchone()[0]
        assert ver >= 2, f"Expected schema version >= 2, got {ver}"
    finally:
        conn.close()


# ── 8. Security: Export Sanitization of Secrets ────────────────

def test_export_sanitizes_secrets_by_default(tmp_path, capsys):
    """Verify that export strips API keys and passwords from config.toml by default."""
    workspace_dir = tmp_path / "workspaces" / "default"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "workspace.db").touch()

    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[groq]\napi_key = "gsk_sensitive_secret_key"\nmodel = "llama-3.3-70b"\n\n'
        '[composio]\napi_key = "ak_sensitive_composio"\n\n'
        '[neo4j]\npassword = "super_secret_password"\n',
        encoding="utf-8"
    )

    export_target = tmp_path / "test_export.zip"
    args = DummyArgs(file=str(export_target), include_secrets=False)

    with patch("cli.commands.export.get_active_profile", return_value="default"), \
         patch("cli.commands.export.get_profile_path", return_value=workspace_dir), \
         patch("cli.commands.export.get_db_path", return_value=workspace_dir / "workspace.db"), \
         patch("cli.commands.export.get_qdrant_path", return_value=workspace_dir / "qdrant"), \
         patch("cli.commands.export.get_neo4j_path", return_value=workspace_dir / "neo4j"), \
         patch("cli.commands.export._get_config_path", return_value=config_file), \
         patch("cli.commands.export.get_workspace_size", return_value=1024):
        
        execute_export(args)

    assert export_target.exists()
    with zipfile.ZipFile(export_target, "r") as zf:
        assert "config.toml" in zf.namelist()
        exported_toml = zf.read("config.toml").decode("utf-8")
        assert "gsk_sensitive_secret_key" not in exported_toml, "Security leak: raw Groq API key in export!"
        assert "ak_sensitive_composio" not in exported_toml, "Security leak: raw Composio API key in export!"
        assert "super_secret_password" not in exported_toml, "Security leak: raw Neo4j password in export!"
        assert 'api_key = ""' in exported_toml

    captured = capsys.readouterr()
    assert "credentials sanitized for security" in captured.out


def test_config_show_masks_secrets(tmp_path, capsys):
    """Verify memory-os config show masks sensitive API keys and passwords."""
    cfg = dict(DEFAULTS)
    cfg["groq"] = {"api_key": "gsk_my_super_secret_groq_key", "model": "llama-3.3-70b-versatile"}
    cfg["neo4j"] = {"password": "secret_password", "user": "neo4j"}

    with patch("cli.commands.config_cmd.get_config", return_value=cfg):
        execute_config(DummyArgs(config_action="show"))

    captured = capsys.readouterr()
    assert "gsk_my_super_secret_groq_key" not in captured.out
    assert "gsk_***" in captured.out or "****" in captured.out
    assert "secret_password" not in captured.out


# ── 9. End-to-End Clean User Environment Simulation ────────────

def test_clean_user_lifecycle_simulation(tmp_path, capsys):
    """Simulates a clean installation lifecycle: empty workspace -> init -> sync -> query."""
    workspace_root = tmp_path / ".memory-os"
    db_file = workspace_root / "workspaces" / "default" / "workspace.db"

    env_overrides = {
        "MEMORY_OS_WORKSPACE": str(workspace_root),
        "MEMORY_OS_DB_PATH": str(db_file),
    }

    with patch.dict(os.environ, env_overrides):
        # 1. Database initialization
        init_db(str(db_file))
        assert db_file.exists()

        # 2. Insert repository, document, and email
        conn = get_connection(str(db_file))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO repositories (repo_name, description, language) VALUES (?, ?, ?)",
            ("memory-os-core", "Core knowledge system", "Python")
        )
        cursor.execute(
            "INSERT INTO repository_documents (repo_name, file_name, content, synced_at) VALUES (?, ?, ?, ?)",
            ("memory-os-core", "README.md", "# Memory-OS Core Architecture\nUses Python, SQLite, Qdrant.", "2026-09-21T00:00:00")
        )
        cursor.execute(
            "INSERT INTO emails (message_id, subject, sender, snippet, received_at) VALUES (?, ?, ?, ?, ?)",
            ("msg-101", "Release Notes v0.1.18", "dev@memory-os.org", "Memory-OS v0.1.18 released.", "2026-09-21T00:00:00")
        )
        conn.commit()
        conn.close()

        # 3. Verify counts
        from storage.db import get_repo_count, get_repository_document_count, get_email_count
        assert get_repo_count() == 1
        assert get_repository_document_count() == 1
        assert get_email_count() == 1

        # 4. Chunker & ranking execution
        from core.chunker import generate_and_save_chunks
        from storage.db import get_document_chunk_count
        generate_and_save_chunks()
        assert get_document_chunk_count() > 0

        # 5. Hybrid search without external Qdrant (keyword + ranking fallback)
        from storage.db import search_local_knowledge_ranked
        results = search_local_knowledge_ranked("Python")
        assert len(results) > 0
        assert any(r["repo_name"] == "memory-os-core" for r in results if "repo_name" in r)


# ── 10. LLM Inference & RAG: Model Selection & Fallback Logic ──

def test_ask_llm_model_selection_and_no_destructive_remapping(tmp_path):
    """Verify configured model (e.g. openai/gpt-oss-120b) is passed directly to Groq client without being remapped."""
    from core.llm import run_hybrid_rag
    db_file = tmp_path / "rag_test.db"
    init_db(str(db_file))

    conn = get_connection(str(db_file))
    conn.execute(
        "INSERT INTO repositories (repo_name, description) VALUES (?, ?)",
        ("Memory-OS", "AI personal operating system")
    )
    conn.execute(
        "INSERT INTO repository_documents (repo_name, file_name, content, synced_at) VALUES (?, ?, ?, ?)",
        ("Memory-OS", "README.md", "Memory-OS is an AI personal operating system.", "2026-10-08T00:00:00")
    )
    conn.commit()
    conn.close()

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Answer: Memory-OS is an AI personal OS.\nSources: Memory-OS/README.md\nRepositories Used: Memory-OS"))]
    mock_client.chat.completions.create.return_value = mock_resp

    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file), "GROQ_MODEL": "openai/gpt-oss-120b"}), \
         patch("core.llm.get_groq_client_and_key", return_value=(mock_client, "fake-groq-key")), \
         patch("core.vector_store.get_qdrant_client", side_effect=Exception("Qdrant offline")):
        
        result = run_hybrid_rag("Memory-OS")
        assert result["answer"] != "", "Answer must not be empty"
        assert "Memory-OS is an AI personal OS" in result["answer"]
        # Assert model passed to Groq was openai/gpt-oss-120b and NOT remapped to llama-3.3-70b-versatile
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "openai/gpt-oss-120b"


def test_ask_llm_fallback_models_actually_attempted():
    """Verify that when a model fails with 404, fallback models are actually attempted."""
    from core.llm import query_llm_with_retry, VALID_GROQ_FALLBACK_MODELS

    mock_client = MagicMock()
    # First model raises 404, second model succeeds
    mock_resp_success = MagicMock()
    mock_resp_success.choices = [MagicMock(message=MagicMock(content="Success from fallback!"))]
    mock_client.chat.completions.create.side_effect = [
        Exception("Error code: 404 - model_not_found"),
        mock_resp_success
    ]

    with patch("core.llm.get_groq_client_and_key", return_value=(mock_client, "fake-groq-key")):
        ans = query_llm_with_retry([{"role": "user", "content": "hi"}], model="non-existent-primary-model")
        assert ans == "Success from fallback!"
        assert mock_client.chat.completions.create.call_count == 2
        # Verify first call was primary model, second call was fallback
        first_call_model = mock_client.chat.completions.create.call_args_list[0][1]["model"]
        second_call_model = mock_client.chat.completions.create.call_args_list[1][1]["model"]
        assert first_call_model == "non-existent-primary-model"
        assert second_call_model == VALID_GROQ_FALLBACK_MODELS[0]


def test_ask_llm_all_models_fail_returns_actionable_error_never_empty(tmp_path):
    """Verify that complete LLM inference failure produces an actionable error and never empty string."""
    from core.llm import run_hybrid_rag
    db_file = tmp_path / "rag_fail_test.db"
    init_db(str(db_file))

    conn = get_connection(str(db_file))
    conn.execute(
        "INSERT INTO repositories (repo_name, description) VALUES (?, ?)",
        ("Memory-OS", "AI personal operating system")
    )
    conn.execute(
        "INSERT INTO repository_documents (repo_name, file_name, content, synced_at) VALUES (?, ?, ?, ?)",
        ("Memory-OS", "README.md", "Some test content.", "2026-10-08T00:00:00")
    )
    conn.commit()
    conn.close()

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("404 - model_not_found across all models")

    with patch.dict(os.environ, {"MEMORY_OS_DB_PATH": str(db_file)}), \
         patch("core.llm.get_groq_client_and_key", return_value=(mock_client, "fake-groq-key")), \
         patch("core.vector_store.get_qdrant_client", side_effect=Exception("Qdrant offline")):
        
        result = run_hybrid_rag("Memory-OS")
        assert result["answer"] != "", "Answer must NEVER be blank on LLM failure"
        assert "Error communicating with Groq:" in result["answer"]
        assert result["confidence"] == 0.0


# ── 11. Packaging Isolation: Include Only Official Packages ─────

def test_packaging_isolation_in_pyproject_toml():
    """Verify that pyproject.toml explicitly restricts package discovery to official packages."""
    import tomllib
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    find_cfg = data["tool"]["setuptools"]["packages"]["find"]
    assert "include" in find_cfg, "pyproject.toml must declare 'include' to prevent packaging bleed"
    includes = find_cfg["include"]
    assert "cli*" in includes
    assert "connectors*" in includes
    assert "core*" in includes
    assert "infrastructure*" in includes
    assert "models*" in includes
    assert "storage*" in includes
    assert "scratch*" not in includes


# ── 12. CLI: Restore Command Alias ──────────────────────────────

def test_restore_command_alias(tmp_path):
    """Verify memory-os restore is parsed and routes to import_cmd with Zip Slip protections."""
    parser = build_parser()
    parsed = parser.parse_args(["restore", "archive.zip"])
    assert parsed.command == "restore"
    assert parsed.file == "archive.zip"

    from cli.commands.restore import execute as execute_restore
    from cli.commands.import_cmd import execute as execute_import
    assert execute_restore == execute_import
