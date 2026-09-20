from __future__ import annotations

from enum import Enum


class PortabilityKind(str, Enum):
    """Classification of a feature's portability across backends."""

    PORTABLE = "portable"

    CAPABILITY_DEPENDENT = "capability_dependent"

    BACKEND_SPECIFIC = "backend_specific"

class Portability:
    """Describes the portability of a feature across backends."""

    __slots__ = ("kind",)

    def __init__(self, kind: PortabilityKind) -> None:
        """Initialize portability with the given kind.

        Parameters
        ----------
        kind:
            The portability classification for the feature.
        """
        self.kind: PortabilityKind = kind

    @property
    def is_portable(self) -> bool:
        """Return whether the feature is fully portable."""
        return self.kind is PortabilityKind.PORTABLE

    @property
    def is_capability_dependent(self) -> bool:
        """Return whether the feature depends on backend capabilities."""
        return self.kind is PortabilityKind.CAPABILITY_DEPENDENT

    @property
    def is_backend_specific(self) -> bool:
        """Return whether the feature is specific to a single backend."""
        return self.kind is PortabilityKind.BACKEND_SPECIFIC

    def __repr__(self) -> str:
        return f"Portability({self.kind.value})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Portability):
            return self.kind is other.kind
        if isinstance(other, PortabilityKind):
            return self.kind is other
        return False
