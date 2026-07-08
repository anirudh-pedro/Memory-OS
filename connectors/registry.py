"""
Connector registry.

Discovers and manages available connectors. In Phase 1 this wraps
the existing sync functions. Future connectors simply subclass
BaseConnector and are auto-discovered.
"""

import logging
from connectors.base import BaseConnector

logger = logging.getLogger("connectors.registry")

# Registry of known connector classes
_connector_classes: list[type[BaseConnector]] = []


def register(cls: type[BaseConnector]):
    """Register a connector class."""
    if cls not in _connector_classes:
        _connector_classes.append(cls)
    return cls


def discover_connectors() -> list[BaseConnector]:
    """Discover and instantiate all registered connectors.

    Imports connector modules to trigger registration, then
    returns instances of all registered connector classes.
    """
    # Import connector modules to trigger @register decorators
    try:
        import connectors.github  # noqa: F401
    except ImportError:
        logger.warning("Could not import connectors.github")

    try:
        import connectors.gmail  # noqa: F401
    except ImportError:
        logger.warning("Could not import connectors.gmail")

    try:
        import connectors.notion  # noqa: F401
    except ImportError:
        logger.warning("Could not import connectors.notion")

    return [cls() for cls in _connector_classes]


def get_connector(name: str) -> BaseConnector | None:
    """Return a connector instance by name."""
    for connector in discover_connectors():
        if connector.name.lower() == name.lower() or connector.slug == name.lower():
            return connector
    return None


def list_connectors() -> list[str]:
    """Return names of all registered connectors."""
    return [cls.name for cls in _connector_classes]
