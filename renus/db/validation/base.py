from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Rule(ABC):
    """Base contract for validation rules.

    A rule is callable and must describe its JSON Schema representation.
    """

    @abstractmethod
    def __call__(self, value: Any) -> Any:
        """Validate ``value`` and return ``True`` or a validation error."""
        raise NotImplementedError

    @abstractmethod
    def json_schema(self) -> dict[str, Any]:
        """Return this rule's JSON Schema fragment."""
        raise NotImplementedError
