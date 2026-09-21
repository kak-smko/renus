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
        error: str | None = None,
        validator: Callable[[Any], Any] | list[Callable[[Any], Any]] | None = None,
        validators: list[Callable[[Any], Any]] | None = None,
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
        error:
            Custom error message template used by compatible validation rules.
        validator:
            Callable or list of callables used as validation rules.
        validators:
            Additional callables used as validation rules.
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
        self.error = error
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
        parsed_rules = list(rules)
        if validator is not None:
            parsed_rules.extend(validator if isinstance(validator, (list, tuple)) else [validator])
        if validators is not None:
            parsed_rules.extend(validators)
        for r in parsed_rules:
            if isinstance(r, type) and issubclass(r, Rule):
                r = r()
            if not isinstance(r, Rule):
                raise TypeError("Validation rules must inherit Rule")
            if hasattr(r, "__class__") and r.__class__.__name__ == "Default":
                if self.default is _UNSET and self.default_factory is None:
                    self.default = r.d
                continue
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
                return is_nullable, (list,), False, False, None

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
            types_to_check.append(list)
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

    def _custom_message(self, context: list[Any]) -> str | None:
        if self.field.error is not None:
            try:
                return self.field.error.format(self.name, *context)
            except (IndexError, KeyError, ValueError):
                return None
        return None

    def clean_and_validate(self, value: Any, owner_cls: type | None = None) -> tuple[Any, list[str]]:
        """Coerce and validate a value, returning it with any error messages."""
        errors: list[str] = []

        if value is None:
            if self.has_default:
                value = self.get_default()

            if value is None:
                if self.is_nullable:
                    return None, []
                if self.required:
                    return None, [f"'{self.name}' is required"]
                return None, []

        for rule in self.field.rules:

            if hasattr(rule, "__class__") and rule.__class__.__name__ == "Convert":
                try:
                    value = rule(value)
                except Exception as e:
                    errors.append(f"Failed to convert '{self.name}': {e}")
                continue

            if callable(rule):
                try:
                    res = rule(value)
                    if res is True:
                        continue
                    elif res is False:
                        errors.append(f"Validation failed for '{self.name}'")
                    elif (
                        isinstance(res, (list, tuple))
                        and len(res) > 0
                        and isinstance(res[0], str)
                        and res[0].endswith("_error")
                    ):
                        errors.append(format_rule_error(self.name, res))
                    elif isinstance(res, list) and all(isinstance(x, (list, tuple)) for x in res):
                        for item in res:
                            errors.append(format_rule_error(self.name, item))
                    else:

                        value = res
                except (ValidationError, ValueError, TypeError) as e:
                    errors.append(str(e))
                except Exception as e:
                    errors.append(f"Validator error on '{self.name}': {e}")

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
                    value = self.model_cls(value)
                except ValidationError as e:
                    for sub_field, sub_errs in e.errors.items():
                        prefix = f"{self.name}.{sub_field}"
                        if isinstance(sub_errs, list):
                            errors.extend(f"{prefix}: {err}" for err in sub_errs)
                        else:
                            errors.append(f"{prefix}: {sub_errs}")
                except Exception as e:
                    errors.append(f"Failed to instantiate {self.model_cls.__name__} for '{self.name}': {e}")
            elif not isinstance(value, self.model_cls):
                errors.append(f"'{self.name}' must be an instance of {self.model_cls.__name__} or a dict")

        elif self.is_model_list and self.model_cls is not None:
            if isinstance(value, list):
                new_list = []
                for idx, item in enumerate(value):
                    if isinstance(item, dict):
                        try:
                            new_list.append(self.model_cls(item))
                        except ValidationError as e:
                            for sub_field, sub_errs in e.errors.items():
                                prefix = f"{self.name}[{idx}].{sub_field}"
                                if isinstance(sub_errs, list):
                                    errors.extend(f"{prefix}: {err}" for err in sub_errs)
                                else:
                                    errors.append(f"{prefix}: {sub_errs}")
                        except Exception as e:
                            errors.append(f"Error at '{self.name}[{idx}]': {e}")
                    elif isinstance(item, self.model_cls):
                        new_list.append(item)
                    else:
                        errors.append(f"'{self.name}[{idx}]' must be a {self.model_cls.__name__} or a dict")
                value = new_list
            else:
                errors.append(f"'{self.name}' must be a list of {self.model_cls.__name__}")

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
                elif target_type is list:
                    if isinstance(value, list):
                        matched = True
                        break
                elif target_type is dict:
                    if isinstance(value, dict):
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
                type_names = ", ".join(
                    getattr(t, "__name__", str(t)) for t in self.effective_types
                )
                errors.append(
                    f"'{self.name}' must be of type {type_names}, got {type(value).__name__}"
                )

        return value, errors
