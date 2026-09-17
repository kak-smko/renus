from __future__ import annotations

from renus.db.validation.engine import Validate


class Schema:
    """Validate a dict against a schema of nested rules."""

    def __init__(self, schema: dict, strict: bool = True):
        self.schema = schema
        self.strict = strict

    def __call__(self, input):
        if input is None:
            return True
        if not isinstance(input, dict):
            return ["type_error", ["dict", str(type(input))]]
        if self.strict:
            extra_fields = set(input.keys()) - set(self.schema.keys())
            if extra_fields:
                return ["schema_strict_error", [list(extra_fields)]]
        input.update(Validate(input).rules(self.schema))
        return True
