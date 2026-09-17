from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from types import MappingProxyType
from typing import Any

from renus.db.models.id import ID

PARAM_REGEX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([^{}]+))?\}")

class BaseConvertor(ABC):
    """Base class for path parameter value convertors."""

    regex: str = r"[^/]+"

    @abstractmethod
    def convert(self, value: str) -> Any:
        """Convert a raw path segment to a typed value."""
        pass

class StringConvertor(BaseConvertor):
    """Convert a path parameter to a string."""

    regex = r"[^/]+"

    def convert(self, value: str) -> str:
        """Return the value unchanged."""
        return value

class PathConvertor(BaseConvertor):
    """Convert a path parameter spanning multiple segments."""

    regex = r"[^/]+(?:/[^/]+)*"

    def convert(self, value: str) -> str:
        """Return the value unchanged."""
        return value

class IDConvertor(BaseConvertor):
    """Convert an ``id:<value>`` path parameter to a configured identity."""

    prefix = "id:"
    regex = rf"{prefix}[^/]+"

    def convert(self, value: str) -> ID:
        """Strip the ``id:`` marker and build an identity value."""
        if not value.startswith(self.prefix):
            raise ValueError("ID route parameter must start with 'id:'")
        return ID(value[len(self.prefix):])


class IntegerConvertor(BaseConvertor):
    """Convert a path parameter to an integer."""

    regex = r"[0-9]+"

    def convert(self, value: str) -> int:
        """Convert the value to ``int``."""
        return int(value)

class FloatConvertor(BaseConvertor):
    """Convert a path parameter to a float."""

    regex = r"[0-9]+(?:\.[0-9]+)?"

    def convert(self, value: str) -> float:
        """Convert the value to ``float``."""
        return float(value)


class BoolConvertor(BaseConvertor):
    """Convert a path parameter to a boolean."""

    regex = r"(?:true|false)"

    def convert(self, value: str) -> bool:
        """Return ``True`` if the value is ``"true"``."""
        return value == "true"

class UuidConvertor(BaseConvertor):
    """Convert a path parameter to a UUID."""

    regex = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    def convert(self, value: str) -> uuid.UUID:
        """Convert the value to ``uuid.UUID``."""
        return uuid.UUID(value)

CONVERTOR_TYPES: Mapping[str, BaseConvertor] = MappingProxyType(
    {
        "str": StringConvertor(),
        "int": IntegerConvertor(),
        "id": IDConvertor(),
        "float": FloatConvertor(),
        "path": PathConvertor(),
        "bool": BoolConvertor(),
        "uuid": UuidConvertor(),
    }
)

def build_path(path: str) -> tuple[re.Pattern[str], dict[str, BaseConvertor]]:
    """Compile a route path pattern into a regex and convertor map.

    Parameters
    ----------
    path:
        URL path pattern containing ``{name:type}`` placeholders.
    """
    path_regex = ""
    idx = 0
    param_convertors: dict[str, BaseConvertor] = {}

    for match in PARAM_REGEX.finditer(path):
        param_name, convertor_type = match.groups("str")
        convertor_type = convertor_type.lstrip(":")
        path_regex += re.escape(path[idx : match.start()])

        convertor = CONVERTOR_TYPES.get(convertor_type)
        if convertor is None:
            raise ValueError(
                f"Unknown route parameter type '{convertor_type}' for "
                f"'{{{param_name}:{convertor_type}}}' in path '{path}'"
            )
        path_regex += f"(?P<{param_name}>{convertor.regex})"
        param_convertors[param_name] = convertor

        idx = match.end()

    path_regex += re.escape(path[idx:])
    return re.compile(path_regex), param_convertors

__all__ = [
    "PARAM_REGEX",
    "CONVERTOR_TYPES",
    "BaseConvertor",
    "StringConvertor",
    "PathConvertor",
    "IntegerConvertor",
    "IDConvertor",
    "FloatConvertor",
    "BoolConvertor",
    "UuidConvertor",
    "build_path",
]
