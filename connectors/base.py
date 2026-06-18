from abc import ABC, abstractmethod
from typing import List
from core.models import Memory

class BaseConnector(ABC):
    @abstractmethod
    def sync(self, session) -> List[Memory]:
        """Fetch data from the external source using Composio session and return list of normalized Memory objects."""
        pass
