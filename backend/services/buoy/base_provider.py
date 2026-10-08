from abc import ABC, abstractmethod
from datetime import datetime
from .buoy_models import Buoy, Observation

class SourceAccessPending(RuntimeError):
    pass

class BuoyDataProvider(ABC):
    @abstractmethod
    async def get_buoys(self) -> list[Buoy]: ...

    @abstractmethod
    async def get_latest_observation(self, buoy_id: str) -> Observation | None: ...

    @abstractmethod
    async def get_history(self, buoy_id: str, start: datetime, end: datetime) -> list[Observation]: ...

    async def refresh(self):
        """Optional single batch refresh before the shared polling cycle."""
