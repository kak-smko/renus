from __future__ import annotations

from datetime import date, datetime
from typing import Any

from renus.db.validation.base import Rule


class Default(Rule):
    """Provide a default value when the input is ``None``."""

    def __init__(self, data):
        self.d = data

    def __call__(self, input):
        if input is None:
            if callable(self.d) and not isinstance(self.d, type):
                return self.d()
            return self.d
        return True

    def json_schema(self) -> dict[str, Any]:
        return {} if callable(self.d) else {"default": self.d}


class Convert(Rule):
    """Convert the input value before further validation."""

    def __init__(self, func=None, inputs: list = None):
        self.func = func
        self.inputs = inputs

    def __call__(self, input):
        if input is None:
            return None
        if self.inputs is not None:
            for item in self.inputs:
                if item[0] == input:
                    return item[1]
            return input
        if self.func is not None:
            if isinstance(self.func, type) and isinstance(input, self.func):
                return input
            if self.func is datetime and isinstance(input, str):
                return datetime.fromisoformat(input)
            if self.func is date and isinstance(input, str):
                return date.fromisoformat(input)
            return self.func(input)
        return input

    def json_schema(self) -> dict[str, Any]:
        if self.func is date:
            return {"format": "date"}
        if self.func is datetime:
            return {"format": "date-time"}
        return {}


class Required(Rule):
    """Pass when the input is not ``None``."""

    is_required = True

    def __call__(self, input) -> Any:
        return True if input is not None else "required_error"

    def json_schema(self) -> dict[str, Any]:
        return {}
