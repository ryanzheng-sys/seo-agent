"""Data collection modules.

Each collector exposes a `collect(...)` method returning typed Pydantic models
and degrades gracefully (logging a warning + returning empty results) when
its upstream credentials aren't configured.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any

from seo_agent.config import DomainConfig


@dataclass
class CollectionWindow:
    """Period of interest for a collector run."""

    start: date
    end: date

    @property
    def previous_start(self) -> date:
        from datetime import timedelta

        return self.start - (self.end - self.start) - timedelta(days=1)

    @property
    def previous_end(self) -> date:
        from datetime import timedelta

        return self.start - timedelta(days=1)


class Collector(ABC):
    """Common interface every collector implements."""

    name: str = "collector"

    @abstractmethod
    def collect(self, domain: DomainConfig, window: CollectionWindow) -> Any:
        """Collect data for a single domain over `window`. Return type is collector-specific."""

    def is_ready(self) -> bool:  # pragma: no cover - trivial default
        """Return True if credentials / config are sufficient to run live."""
        return True
