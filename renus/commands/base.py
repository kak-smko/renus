from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

class BaseCommand(ABC):
    """Abstract base class for CLI commands."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, args: list[str] | None = None) -> int | None:
        """Execute the command and return an optional exit code."""
        pass
