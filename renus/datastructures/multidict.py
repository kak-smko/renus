from __future__ import annotations

import copy as _copy
from typing import (
    Any,
    Generic,
    ItemsView,
    Iterator,
    KeysView,
    Mapping,
    TypeVar,
    ValuesView,
)

KT = TypeVar("KT")
VT = TypeVar("VT")

def _grouped(items: list[tuple[KT, VT]]) -> dict[KT, list[VT]]:
    groups: dict[KT, list[VT]] = {}
    for key, value in items:
        groups.setdefault(key, []).append(value)
    return {key: sorted(values, key=repr) for key, values in groups.items()}

class MultiDict(Mapping[KT, VT], Generic[KT, VT]):
    """A mapping that retains multiple values for the same key."""

    __slots__ = ("_dict", "_list")

    def __init__(
        self,
        values: "MultiDict[KT, VT] | Mapping[KT, VT] | list[tuple[KT, VT]] | None" = None,
        **kwargs: Any,
    ) -> None:
        """Populate the mapping from the given values and keyword arguments.

        Parameters
        ----------
        values:
            Optional initial data: another MultiDict, a mapping, a list of
            ``(key, value)`` pairs, or ``None``.
        **kwargs:
            Additional key/value pairs merged into the mapping.
        """
        if isinstance(values, MultiDict):
            items: list[tuple[Any, Any]] = list(values.multi_items())
        elif isinstance(values, Mapping):
            items = list(values.items())
        elif values is not None:
            items = list(values)
        else:
            items = []
        if kwargs:
            items = items + list(kwargs.items())

        self._dict: dict[KT, VT] = {k: v for k, v in items}

        self._list: list[tuple[KT, VT]] = items

    def __getitem__(self, key: KT) -> VT:
        """Return the value stored for the given key."""
        return self._dict[key]

    def __iter__(self) -> Iterator[KT]:
        """Iterate over the stored keys."""
        return iter(self._dict)

    def __len__(self) -> int:
        """Return the number of stored keys."""
        return len(self._dict)

    def __contains__(self, key: object) -> bool:
        """Return whether the given key is present."""
        return key in self._dict

    def __bool__(self) -> bool:
        """Return whether the mapping holds any values."""
        return bool(self._list)

    def keys(self) -> KeysView[KT]:
        """Return a view of the stored keys."""
        return self._dict.keys()

    def values(self) -> ValuesView[VT]:
        """Return a view of the stored values."""
        return self._dict.values()

    def items(self) -> ItemsView[KT, VT]:
        """Return a view of the stored key/value pairs."""
        return self._dict.items()

    def get(self, key: KT, default: VT | None = None) -> VT | None:
        """Return the value for a key, or ``default`` if absent."""
        return self._dict.get(key, default)

    def multi_items(self) -> list[tuple[KT, VT]]:
        """Return all ``(key, value)`` pairs, including duplicates."""
        return list(self._list)

    def getlist(self, key: KT) -> list[VT]:
        """Return all values stored for the given key."""
        return [value for k, value in self._list if k == key]

    def copy(self) -> "MultiDict[KT, VT]":
        """Return a shallow copy of this mapping."""
        return type(self)(list(self._list))

    __copy__ = copy

    def __deepcopy__(self, memo: dict[int, Any]) -> "MultiDict[KT, VT]":
        """Return a deep copy of this mapping."""
        cls = type(self)
        result = cls.__new__(cls)
        result._list = _copy.deepcopy(self._list, memo)
        result._dict = dict(result._list)
        memo[id(self)] = result
        return result

    def __eq__(self, other: object) -> bool:
        """Compare against another MultiDict or mapping."""
        if isinstance(other, MultiDict):
            return _grouped(self._list) == _grouped(other._list)
        if isinstance(other, Mapping):
            return _grouped(self._list) == _grouped(list(other.items()))
        return NotImplemented

    def __or__(self, other: Mapping[KT, VT]) -> "MultiDict[KT, VT]":
        """Merge this mapping with another, keeping duplicate values."""
        if isinstance(other, MultiDict):
            other_items = list(other.multi_items())
        else:
            other_items = list(other.items())
        return type(self)(list(self._list) + other_items)

    def __repr__(self) -> str:
        """Return a string representation of this mapping."""
        return f"{type(self).__name__}({self._list!r})"
