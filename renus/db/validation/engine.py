from __future__ import annotations

import copy

from renus.db.validation.base import Rule
from renus.response import abort_if
from renus.log import Log


def keys_exists(element, keys):
    """Resolve a nested value, creating missing keys along the path."""
    if not isinstance(element, dict):
        raise AttributeError("keys_exists() expects dict as first argument.")
    if len(keys) == 0:
        raise AttributeError("keys_exists() expects at least two arguments, one given.")

    current = element
    for index, key in enumerate(keys):
        try:
            current = current[key]
        except KeyError:
            current[key] = None if index == len(keys) - 1 else {}
            current = current[key]
    return current


def set_key(result, keys, value):
    """Set a nested value, creating intermediate keys as needed."""
    current = result
    for index, key in enumerate(keys):
        if index == len(keys) - 1:
            current[key] = value
            return
        current = current.setdefault(key, {})


class Validate:
    """Validate form data against a set of rules."""

    def __init__(self, form: dict, break_on_error: bool = False, log_on_error: bool = False) -> None:
        self._form = copy.deepcopy(form)
        self._break_on_error = break_on_error
        self._log_on_error = log_on_error
        self._error = False
        self._msg = {}

    def rules(self, rules_data: dict, msg: str = "invalid_data") -> dict:
        result = {}
        for field, field_rules in rules_data.items():
            keys = field.split(".")
            value = keys_exists(self._form, keys)

            check = self._check(value, field_rules)
            if check is True:
                set_key(result, keys, value)
            else:
                self._error = True
                self._msg[field] = check
                if self._break_on_error:
                    break

        if self._log_on_error:
            Log().error({"msg": msg, "errors": self._msg})
        abort_if(self._error, {"msg": msg, "errors": self._msg}, 422)
        return result

    def _check(self, value, rules):
        error = False
        messages = []
        for rule in rules:
            if isinstance(rule, type) and issubclass(rule, Rule):
                rule = rule()
            if not isinstance(rule, Rule):
                raise TypeError("Validation rules must inherit Rule")
           
            test = rule(value)
            if test is not True:
                error = True
                messages.append(test)
        return True if not error else messages
