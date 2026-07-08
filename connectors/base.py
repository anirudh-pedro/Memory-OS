"""
Connector plugin interface.

All connectors must subclass BaseConnector and implement
authenticate(), sync(), and health() methods.
"""

from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Interface that all Memory-OS connectors must implement."""

    name: str = ""
    slug: str = ""

    @abstractmethod
    def authenticate(self) -> bool:
        """Check if authentication is active for this connector.

        Returns True if the connector is authenticated and ready to sync.
        """
        ...

    @abstractmethod
    def sync(self) -> dict:
        """Run the sync process for this connector.

        Returns a summary dict with keys like 'synced', 'skipped', 'errors'.
        """
        ...

    @abstractmethod
    def health(self) -> tuple[bool, str]:
        """Check the health/connectivity status of this connector.

        Returns (is_healthy, detail_string).
        """
        ...
