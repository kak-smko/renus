from __future__ import annotations


import sys
import types
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from renus.config import Config
from renus.datastructures.id import ID, is_identity

if TYPE_CHECKING:
    from renus.db.models.db_field import DatabaseField

from renus.db.core.exceptions import ValidationError
from renus.db.validation.base import Rule

class _Unset:
    def __repr__(self) -> str:
        return "<UNSET>"

_UNSET = _Unset()

def _is_model_type(value: Any) -> bool:
    return isinstance(value, type) and bool(getattr(value, "_is_model_class", False))

def find_model_subclass(name: str, model_base: type | None = None) -> type | None:
    if model_base is None:
        return None

    def _search(cls: type) -> type | None:
        for sub in cls.__subclasses__():
            if sub.__name__ == name:
                return sub
            found = _search(sub)
            if found is not None:
                return found
        return None

    return _search(model_base)


def _split_type_arguments(value: str, delimiter: str = ",") -> list[str]:
    """Split an annotation at top-level delimiters, preserving nested types."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == delimiter and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _resolve_type_annotation(annotation: Any, model_base: type | None = None) -> Any:
    """Resolve the common built-in generic forms used by postponed annotations."""
    if not isinstance(annotation, str):
        return annotation

    raw = annotation.strip()
    if "|" in raw:
        parts = _split_type_arguments(raw, "|")
        resolved = tuple(
            type(None) if part in ("None", "NoneType") else _resolve_type_annotation(part, model_base)
            for part in parts
        )
        return Union[resolved]

    primitives = {
        "Any": Any,
        "object": object,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "None": type(None),
        "NoneType": type(None),
    }
    if raw in primitives:
        return primitives[raw]

    open_bracket = raw.find("[")
    if open_bracket > 0 and raw.endswith("]"):
        name = raw[:open_bracket].strip().rsplit(".", 1)[-1]
        arguments = [
            _resolve_type_annotation(part, model_base)
            for part in _split_type_arguments(raw[open_bracket + 1:-1])
        ]
        origin = {"list": list, "List": list, "dict": dict, "Dict": dict}.get(name)
        if origin is not None:
            try:
                return types.GenericAlias(origin, tuple(arguments))
            except TypeError:
                return origin

    model = find_model_subclass(raw, model_base)
    return model if model is not None else object


def _typed_value_errors(value: Any, expected_type: Any) -> list[Any]:
    """Return type errors for a value and a possibly nested generic type."""
    origin = get_origin(expected_type)
    arguments = get_args(expected_type)

    if origin in (Union, types.UnionType):
        if any(not _typed_value_errors(value, option) for option in arguments):
            return []
        expected = " | ".join(getattr(option, "__name__", str(option)) for option in arguments)
        return [["type_error", [expected, type(value).__name__]]]

    if origin is dict:
        if not isinstance(value, dict):
            return [["type_error", ["dict", type(value).__name__]]]
        if len(arguments) < 2:
            return []
        errors: list[Any] = []
        for key, item in value.items():
            errors.extend(_typed_value_errors(key, arguments[0]))
            errors.extend(_typed_value_errors(item, arguments[1]))
        return errors

    if origin is list:
        if not isinstance(value, list):
            return [["type_error", ["list", type(value).__name__]]]
        if not arguments:
            return []
        errors = []
        for item in value:
            errors.extend(_typed_value_errors(item, arguments[0]))
        return errors

    if expected_type in (Any, object):
        return []
    if expected_type is int:
        matches = isinstance(value, int) and not isinstance(value, bool)
    elif expected_type is float:
        matches = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif isinstance(expected_type, type):
        matches = isinstance(value, expected_type)
    else:
        matches = True

    if matches:
        return []
    expected = getattr(expected_type, "__name__", str(expected_type))
    return [["type_error", [expected, type(value).__name__]]]


def format_rule_error(field: str, err: Any) -> str:
    if isinstance(err, str):
        if err == "required_error":
            return f"'{field}' is required"
        return err

    if isinstance(err, (list, tuple)) and len(err) > 0:
        code = err[0]
        args = err[1] if len(err) > 1 else []

        if code == "required_error":
            return f"'{field}' is required"
        if code == "type_error":
            expected = args[0] if len(args) > 0 else "correct type"
            return f"'{field}' must be of type {expected}"
        if code == "min_len_error":
            min_l = args[0] if len(args) > 0 else "?"
            return f"'{field}' length must be at least {min_l}"
        if code == "max_len_error":
            max_l = args[0] if len(args) > 0 else "?"
            return f"'{field}' length must be at most {max_l}"
        if code == "len_error":
            expected_l = args[0] if len(args) > 0 else "?"
            return f"'{field}' length must be {expected_l}"
        if code == "min_error":
            min_v = args[0] if len(args) > 0 else "?"
            return f"'{field}' must be greater than or equal to {min_v}"
        if code == "max_error":
            max_v = args[0] if len(args) > 0 else "?"
            return f"'{field}' must be less than or equal to {max_v}"
        if code == "eq_error":
            eq_v = args[0] if len(args) > 0 else "?"
            return f"'{field}' must be equal to {eq_v}"
        if code in ("email_at_error", "email_domain_name_error", "email_name_error"):
            return f"'{field}' is not a valid email address"
        if code == "email_domain_allow_error":
            domain = args[0] if len(args) > 0 else ""
            allowed = args[1] if len(args) > 1 else ""
            return f"'{field}' email domain '{domain}' is not allowed (allowed: {allowed})"
        if code == "regex_error":
            return f"'{field}' does not match the required pattern"
        if code == "in_error":
            return f"'{field}' must be one of {args[1] if len(args) > 1 else ''}"
        if code == "not_in_error":
            return f"'{field}' must not be in {args[1] if len(args) > 1 else ''}"

    return str(err)

class Field:
    """Declares validation and coercion rules for a model field."""

    def __init__(
        self,
        *rules: Any,
        default: Any = _UNSET,
        default_factory: Callable[[], Any] | None = None,
        description: str | None = None,
        database: DatabaseField | None = None,
        sensitive: bool = False,
        **extra: Any,
    ) -> None:
        """Configure the field's validation rules and metadata.

        Parameters
        ----------
        *rules:
            Positional validation rules; callables or error-compatible objects.
        default:
            Static default value used when no value is provided.
        default_factory:
            Zero-argument callable producing a default value.
        description:
            Human-readable description of the field.
        database:
            Optional ``DatabaseField`` with physical column metadata.
        sensitive:
            When true, reads of this attribute return a masked value.
        **extra:
            Additional keyword attributes stored on the field.
        """
        self.sensitive = sensitive
        self.default = default
        self.default_factory = default_factory
        self.description = description
        self.database = database
        if is_identity(self.default_factory) and self.database is not None:
            configured_id = Config("database").get("ID", int)
            if configured_id is int:
                self.database = replace(self.database, auto_inc=True)
                self.default_factory = None
            else:
                self.database = replace(self.database, auto_inc=False)

        self.extra = extra
        self.rules: list[Any] = []
        for r in rules:
            if isinstance(r, type) and issubclass(r, Rule):
                r = r()
            if not isinstance(r, Rule):
                raise TypeError("Validation rules must inherit Rule")
            self.rules.append(r)

class FieldInfo:
    """Precomputed metadata describing a declared model field."""

    def __init__(
        self,
        name: str,
        field_type: Any,
        field: Field | None = None,
        default: Any = _UNSET,
        model_base: type | None = None,
    ) -> None:
        """Resolve the field's type, defaults, and validation setup.

        Parameters
        ----------
        name:
            Attribute name of the field on the model.
        field_type:
            Declared annotation type of the field.
        field:
            Optional ``Field`` holding validation rules. When omitted, one is
            created using the given default.
        default:
            Default value applied to the field when not provided.

        model_base:
            Base model class used to resolve forward references.
        """
        self.name = name
        self.field_type = field_type
        self.field = field or Field(default=default)

        if self.field.default is _UNSET and default is not _UNSET:
            self.field.default = default

        self.is_nullable, self.effective_types, self.is_model, self.is_model_list, self.model_cls = (
            self._analyze_type(field_type, model_base=model_base)
        )

        self.required = not self.is_nullable and not self.has_default

    @classmethod
    def _resolve_model_name(
        cls,
        name: str,
        model_base: type | None,
    ) -> type | None:
        frame = sys._getframe()
        while frame is not None:
            candidate = frame.f_locals.get(name)
            if _is_model_type(candidate) and candidate is not model_base:
                return candidate
            frame = frame.f_back
        return find_model_subclass(name, model_base)

    @classmethod
    def _analyze_type(
        cls,
        annotation: Any,
        model_base: type | None = None,
    ) -> tuple[bool, tuple[Any, ...], bool, bool, type | None]:
        if annotation is None or annotation is Any:
            return True, (object,), False, False, None

        is_nullable = False
        types_to_check: list[Any] = []
        is_model = False
        is_model_list = False
        model_cls: type | None = None

        if isinstance(annotation, str):
            raw = annotation.strip()

            if "None" in raw:
                parts = [p.strip() for p in raw.split("|") if p.strip()]
                if "None" in parts or "NoneType" in parts:
                    is_nullable = True
                    parts = [p for p in parts if p not in ("None", "NoneType")]
                    if len(parts) == 1:
                        raw = parts[0]

            if raw.startswith("list[") and raw.endswith("]"):
                inner = raw[5:-1].strip()
                sub = cls._resolve_model_name(inner, model_base)
                if sub is not None:
                    return is_nullable, (list,), False, True, sub
                return is_nullable, (_resolve_type_annotation(raw, model_base),), False, False, None
            if raw.startswith("dict[") and raw.endswith("]"):
                return is_nullable, (_resolve_type_annotation(raw, model_base),), False, False, None

            sub = cls._resolve_model_name(raw, model_base)
            if sub is not None:
                return is_nullable, (sub,), True, False, sub

            primitive_map = {
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "date": date,
                "datetime": datetime,
            }
            if raw in primitive_map:
                return is_nullable, (primitive_map[raw],), False, False, None

            return is_nullable, (object,), False, False, None

        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is types.UnionType or origin is Union or (
            origin is not None and getattr(origin, "__name__", "") == "Union"
        ):
            for arg in args:
                if arg is type(None):
                    is_nullable = True
                elif isinstance(arg, str):
                    _, sub_types, sub_is_model, sub_is_list, sub_model_cls = cls._analyze_type(
                        arg, model_base=model_base
                    )
                    types_to_check.extend(sub_types)
                    if sub_is_model:
                        is_model = True
                        model_cls = sub_model_cls
                    if sub_is_list:
                        is_model_list = True
                        model_cls = sub_model_cls
                else:
                    types_to_check.append(arg)
        elif origin is list:
            types_to_check.append(annotation)
            if args:
                elem_type = args[0]
                if isinstance(elem_type, type) and hasattr(elem_type, "_is_model_class"):
                    is_model_list = True
                    model_cls = elem_type
                elif isinstance(elem_type, str):
                    sub = find_model_subclass(elem_type.strip(), model_base)
                    if sub is not None:
                        is_model_list = True
                        model_cls = sub

        elif origin is dict:
            types_to_check.append(annotation)
        else:
            types_to_check.append(annotation)

        for t in types_to_check:
            if isinstance(t, type) and hasattr(t, "_is_model_class"):
                is_model = True
                model_cls = t
                break

        return is_nullable, tuple(types_to_check), is_model, is_model_list, model_cls

    @property
    def has_default(self) -> bool:
        """Return whether the field defines a default value or factory."""
        return self.field.default is not _UNSET or self.field.default_factory is not None

    def get_default(self) -> Any:
        """Return the field's resolved default value, or ``None`` if unset."""
        if self.field.default_factory is not None:
            return self.field.default_factory()
        if self.field.default is not _UNSET:
            if callable(self.field.default) and not isinstance(self.field.default, type):
                return self.field.default()
            return self.field.default
        return None


    def clean_and_validate(self, value: Any, owner_cls: type | None = None) -> tuple[Any, list[Any]]:
        """Coerce and validate a value, returning it with any error details."""
        errors: list[Any] = []

        if value is None:
            if self.has_default:
                value = self.get_default()

            if value is None:
                if self.is_nullable:
                    return None, []
                if self.required:
                    return None, ["required_error"]
                return None, []

        for rule in self.field.rules:
            if callable(rule):
                try:
                    res = rule(value)
                    if res is True:
                        continue
                    elif res is False:
                        errors.append("validation_error")
                    elif isinstance(res, str) and res.endswith("_error"):
                        errors.append(res)
                    elif (
                        isinstance(res, (list, tuple))
                        and len(res) > 0
                        and isinstance(res[0], str)
                        and res[0].endswith("_error")
                    ):
                        errors.append(list(res))
                    elif isinstance(res, list) and all(isinstance(x, (list, tuple)) for x in res):
                        for item in res:
                            errors.append(list(item))
                    else:

                        value = res
                except Exception:
                    if "internal_error" not in errors:
                        errors.append("internal_error")

        f = self.field

        if (
            value is not None
            and type(value).__name__ == "ID"
            and not isinstance(value, ID)
        ):
            if ID in self.effective_types:
                value = ID(str(value))
            elif str in self.effective_types:
                value = str(value)

        if self.is_model and self.model_cls is not None:
            if isinstance(value, dict):
                try:
                    from renus.db.serialization.core import from_dict

                    value = from_dict(self.model_cls, value)
                except ValidationError as e:
                    for sub_errs in e.errors.values():
                        if isinstance(sub_errs, list):
                            errors.extend(sub_errs)
                        else:
                            errors.append(sub_errs)
                except Exception:
                    errors.append("internal_error")
            elif not isinstance(value, self.model_cls):
                errors.append(["type_error", [self.model_cls.__name__, type(value).__name__]])

        elif self.is_model_list and self.model_cls is not None:
            if isinstance(value, list):
                new_list = []
                for idx, item in enumerate(value):
                    if isinstance(item, dict):
                        try:
                            from renus.db.serialization.core import from_dict

                            new_list.append(from_dict(self.model_cls, item))
                        except ValidationError as e:
                            for sub_errs in e.errors.values():
                                if isinstance(sub_errs, list):
                                    errors.extend(sub_errs)
                                else:
                                    errors.append(sub_errs)
                        except Exception:
                            errors.append("internal_error")
                    elif isinstance(item, self.model_cls):
                        new_list.append(item)
                    else:
                        errors.append(["type_error", [self.model_cls.__name__, type(item).__name__]])
                value = new_list
            else:
                errors.append(["type_error", [f"list[{self.model_cls.__name__}]", type(value).__name__]])

        elif self.effective_types and not self.is_model and not self.is_model_list:
            matched = False
            for target_type in self.effective_types:
                if target_type is int:
                    if isinstance(value, int) and not isinstance(value, bool):
                        matched = True
                        break
                elif target_type is float:
                    if isinstance(value, (float, int)) and not isinstance(value, bool):
                        matched = True
                        break
                elif target_type is str:
                    if isinstance(value, str):
                        matched = True
                        break
                elif target_type is bool:
                    if isinstance(value, bool):
                        matched = True
                        break
                elif target_type is list or get_origin(target_type) is list:
                    if isinstance(value, list):
                        item_types = get_args(target_type)
                        if item_types:
                            item_type = item_types[0]
                            converted_items = []
                            for item in value:
                                
                                errors.extend(_typed_value_errors(item, item_type))
                                converted_items.append(item)
                            value = converted_items
                        matched = True
                        break
                elif target_type is dict or get_origin(target_type) is dict:
                    if isinstance(value, dict):
                        errors.extend(_typed_value_errors(value, target_type))
                        matched = True
                        break
                elif target_type is date:
                    if isinstance(value, (date, datetime)):
                        matched = True
                        break
                elif target_type is datetime:
                    if isinstance(value, datetime):
                        matched = True
                        break
                elif isinstance(target_type, type) and isinstance(value, target_type):
                    matched = True
                    break
                elif target_type is object or target_type is Any:
                    matched = True
                    break

            if not matched and self.effective_types != (object,):
                expected_types = [
                    getattr(t, "__name__", str(t)) for t in self.effective_types
                ]
                expected = expected_types[0] if len(expected_types) == 1 else expected_types
                errors.append(["type_error", [expected, type(value).__name__]])

        return value, errors
