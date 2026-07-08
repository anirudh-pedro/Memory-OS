"""
Infrastructure: Configuration management.

Implements config priority chain:
    CLI Flags -> config.toml -> .env -> Defaults

Config is loaded once at startup and exported to os.environ so existing
modules (llm.py, graph.py, vector_store.py) work without changes.
"""

import os
import tomllib
from pathlib import Path
from dotenv import load_dotenv

# Default configuration values
DEFAULTS = {
    "workspace": "~/.memory-os",
    "active_profile": "default",
    "composio": {
        "api_key": "",
        "user_id": "",
    },
    "groq": {
        "api_key": "",
        "model": "llama-3.3-70b-versatile",
    },
    "neo4j": {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "",
        "port_http": 7474,
        "port_bolt": 7687,
    },
    "qdrant": {
        "url": "http://localhost:6333",
        "port": 6333,
    },
    "embeddings": {
        "model": "all-MiniLM-L6-v2",
    },
}

_config = None


def _get_config_path() -> Path:
    """Return the path to the config.toml file."""
    workspace_root = Path(os.path.expanduser(
        os.getenv("MEMORY_OS_WORKSPACE", "~/.memory-os")
    ))
    return workspace_root / "config.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(cli_overrides: dict | None = None) -> dict:
    """Load configuration using the priority chain.

    Priority (highest to lowest):
        1. cli_overrides dict
        2. ~/.memory-os/config.toml
        3. .env file (loaded into os.environ)
        4. DEFAULTS

    After merging, key values are exported to os.environ so that
    existing modules pick them up transparently.
    """
    global _config

    # Start with defaults
    config = dict(DEFAULTS)
    for k, v in DEFAULTS.items():
        if isinstance(v, dict):
            config[k] = dict(v)

    # Layer 3: Load .env (lowest priority, loaded into os.environ)
    load_dotenv(override=False)

    # Layer 2: Load config.toml if it exists
    config_path = _get_config_path()
    if config_path.exists():
        with open(config_path, "rb") as f:
            toml_config = tomllib.load(f)
        config = _deep_merge(config, toml_config)

    # Layer 1: CLI overrides (highest priority)
    if cli_overrides:
        config = _deep_merge(config, cli_overrides)

    # Export key values to os.environ for backwards compatibility
    _export_to_environ(config)

    _config = config
    return config


def _export_to_environ(config: dict):
    """Export configuration values to os.environ.

    This ensures existing modules that read os.getenv() continue
    to work without modification.
    """
    # Groq
    groq = config.get("groq", {})
    if groq.get("api_key"):
        os.environ.setdefault("GROQ_API_KEY", groq["api_key"])
    if groq.get("model"):
        os.environ.setdefault("GROQ_MODEL", groq["model"])

    # Composio
    composio = config.get("composio", {})
    if composio.get("api_key"):
        os.environ.setdefault("COMPOSIO_API_KEY", composio["api_key"])

    # Neo4j
    neo4j = config.get("neo4j", {})
    if neo4j.get("uri"):
        os.environ.setdefault("NEO4J_URI", neo4j["uri"])
    if neo4j.get("user"):
        os.environ.setdefault("NEO4J_USER", neo4j["user"])
    if neo4j.get("password"):
        os.environ.setdefault("NEO4J_PASSWORD", neo4j["password"])
    # Port env vars for docker-compose
    os.environ.setdefault("NEO4J_HTTP_PORT", str(neo4j.get("port_http", 7474)))
    os.environ.setdefault("NEO4J_BOLT_PORT", str(neo4j.get("port_bolt", 7687)))

    # Qdrant
    qdrant = config.get("qdrant", {})
    if qdrant.get("url"):
        os.environ.setdefault("QDRANT_URL", qdrant["url"])
    os.environ.setdefault("QDRANT_PORT", str(qdrant.get("port", 6333)))


def get_config() -> dict:
    """Return the currently loaded config, loading it if necessary."""
    global _config
    if _config is None:
        load_config()
    return _config


def get(section: str, key: str, default=None):
    """Read a specific config value. Example: get('groq', 'model')"""
    config = get_config()
    section_dict = config.get(section, {})
    if isinstance(section_dict, dict):
        return section_dict.get(key, default)
    return default


def save_config(config_dict: dict):
    """Write configuration to ~/.memory-os/config.toml."""
    import tomllib  # read-only; we write manually for now
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for key, value in config_dict.items():
        if isinstance(value, dict):
            lines.append(f"\n[{key}]")
            for k, v in value.items():
                lines.append(f'{k} = {_toml_value(v)}')
        else:
            lines.append(f'{key} = {_toml_value(value)}')

    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_value(section: str, key: str, value):
    """Update a single config key and save."""
    config = get_config()
    if section not in config:
        config[section] = {}
    config[section][key] = value
    save_config(config)


def get_dotted(key: str, default=None):
    """Fetch value from config dictionary using dotted path, e.g., 'groq.model' or 'workspace'."""
    config = get_config()
    parts = key.split(".")
    
    current = config
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def set_dotted(key: str, value) -> tuple[bool, str]:
    """Set value in config dictionary using dotted path, e.g., 'groq.model' or 'workspace'.
    Performs type and schema validations. Returns (success, error_message).
    """
    config = get_config()
    parts = key.split(".")
    
    if len(parts) == 1:
        t_key = parts[0]
        if t_key not in DEFAULTS:
            return False, f"Invalid configuration key '{t_key}'"
        if t_key == "workspace" and not value:
            return False, "Workspace path cannot be empty"
        config[t_key] = value
    elif len(parts) == 2:
        section, prop = parts[0], parts[1]
        if section not in DEFAULTS or prop not in DEFAULTS[section]:
            return False, f"Invalid configuration key '{key}'"
            
        default_val = DEFAULTS[section][prop]
        if isinstance(default_val, int):
            try:
                value = int(value)
                if value <= 0:
                    raise ValueError()
            except ValueError:
                return False, f"Configuration key '{key}' must be a positive integer"
        elif isinstance(default_val, bool):
            if str(value).lower() in ("true", "1", "yes", "y"):
                value = True
            elif str(value).lower() in ("false", "0", "no", "n"):
                value = False
            else:
                return False, f"Configuration key '{key}' must be a boolean value"
                
        if section not in config:
            config[section] = {}
        config[section][prop] = value
    else:
        return False, f"Configuration key depth '{key}' not supported"

    save_config(config)
    return True, ""



def generate_default_config(answers: dict) -> dict:
    """Create initial config from prompted values during init.

    ``answers`` should contain keys like 'groq_api_key',
    'composio_api_key', 'neo4j_password', 'composio_user_id'.
    """
    import copy
    config = copy.deepcopy(DEFAULTS)

    if answers.get("groq_api_key"):
        config["groq"]["api_key"] = answers["groq_api_key"]
    if answers.get("composio_api_key"):
        config["composio"]["api_key"] = answers["composio_api_key"]
    if answers.get("composio_user_id"):
        config["composio"]["user_id"] = answers["composio_user_id"]
    if answers.get("neo4j_password"):
        config["neo4j"]["password"] = answers["neo4j_password"]

    return config


def _toml_value(value) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(value, str):
        return f'"{value}"'
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, float):
        return str(value)
    else:
        return f'"{value}"'
