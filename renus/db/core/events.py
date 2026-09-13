from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from renus.db.core.state import Lifecycle

__all__ = [
    "Event",
    "EventBus",
    "EventListener",
    "LifecycleEvent",
    "MutationEvent",
    "QueryEvent",
]

@dataclass(frozen=True, slots=True)
class Event:
    """Base class for events emitted by the database layer."""
    pass

EventListener = Callable[[Event], "Awaitable[None] | None"]

@dataclass(frozen=True, slots=True)
class QueryEvent(Event):
    """Event emitted when a query is executed."""

    adapter: str
    query_type: str
    duration: float
    error: Exception | None = None

@dataclass(frozen=True, slots=True)
class MutationEvent(Event):
    """Event emitted when a mutation is executed."""

    adapter: str
    operation: str
    duration: float
    rows_affected: int = 0
    error: Exception | None = None

@dataclass(frozen=True, slots=True)
class LifecycleEvent(Event):
    """Event emitted on a model lifecycle state change."""

    model: Any
    state: Lifecycle

@dataclass(slots=True)
class EventBus:
    """Registry and dispatcher for named event listeners."""

    _hooks: dict[str, list[EventListener]] = field(default_factory=dict)

    def on(self, name: str, callback: EventListener) -> None:
        """Register a callback for the named event."""
        hooks = self._hooks.setdefault(name, [])
        if callback not in hooks:
            hooks.append(callback)

    def off(self, name: str, callback: EventListener) -> None:
        """Unregister a callback for the named event."""
        hooks = self._hooks.get(name)
        if hooks is not None:
            try:
                hooks.remove(callback)
            except ValueError:
                pass

    async def emit(self, name: str, event: Event) -> None:
        """Dispatch an event to all listeners for the given name."""
        for callback in self._hooks.get(name, ()):
            result = callback(event)
            if isinstance(result, Awaitable):
                await result
