"""Configurable identity type for model primary keys.

``ID`` is the annotation used for generated primary keys::

    class User(Model):
        id: ID

The concrete identity object is read from ``Config("database")`` under ``ID``
and may be ``int``, ``bson.ObjectId``, ``uuid.UUID``, ``str``, or any callable
that mints a unique value. An ``ID`` instance wraps the resolved value, so the
model stores a small value object whose string form is the identity itself.
Encoding and decoding are performed by the adapters: a document store keeps the
identity in its native form (a MongoDB ``ObjectId`` stays an ``ObjectId``),
while a relational store keeps it as text.

An integer identity is never minted here. It is allocated by the backend, either
through native auto increment or, for document stores without one, through a
sequence allocator such as ``MongoDBAdapter._next_sequence``.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID, uuid4

from renus.config import Config

__all__ = ["ID", "is_identity"]


class ID:
    """Identity value resolved from the configured identity object."""

    __renus_identity__: ClassVar[bool] = True

    def __init__(self, value: Any = None) -> None:
        """Wrap ``value``, or mint a new identity when it is ``None``.

        Parameters
        ----------
        value:
            Existing identity value to wrap. When ``None``, a new identity is
            generated (and for an integer identity, left to the backend).
        """
        self.obj = Config("database").get("ID", int)
        if isinstance(value, ID):
            value = value.value
        self.value = self.next() if value is None else self._coerce(value)

    def next(self) -> Any:
        """Return a fresh identity value.

        Integer identities return ``None`` so the adapter allocates the value.

        Raises
        ------
        TypeError
            The configured identity has no usable factory.
        ValueError
            The configured factory returned no value.
        """
        obj = self.obj
        if obj is int:
            return None
        if obj is None:
            raise TypeError(
                f"Identity '{obj}' cannot generate a value; configure a factory "
                f"for ID in Config('database')"
            )

        if obj is UUID:
            value = uuid4()
        elif obj is str:
            value = uuid4().hex
        else:
            value = obj()

        if value is None:
            raise ValueError(f"Identity '{obj}' factory returned no value")
        return value

    def _coerce(self, value: Any) -> Any:
        """Coerce ``value`` into the configured identity type."""
        obj = self.obj
        if isinstance(value, obj):
            return value
        return obj(value)

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"ID({self.value!r})"

    def __bool__(self) -> bool:
        return bool(self.value)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ID):
            return self.value == other.value
        return self.value == other

    def __hash__(self) -> int:
        return hash(self.value)


def is_identity(value: Any) -> bool:
    """Return whether ``value`` is the ``ID`` type or an ``ID`` instance."""
    return value is ID or isinstance(value, ID)
