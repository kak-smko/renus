from datetime import datetime, timezone
from typing import Any

from renus.db.core.exceptions import ValidationError
from renus.db.query.ast import  Path

def normalize_values(values: dict[Any, Any]) -> dict[str, Any]:
    """Map each value to its final leaf field name."""
    normalized: dict[str, Any] = {}
    for key, val in values.items():
        if isinstance(key, Path):
            normalized[key.parts[-1]] = val
        elif isinstance(key, str):
            normalized[key.split(".")[-1]] = val
        else:
            normalized[str(key)] = val
    return normalized


def validate_update_values(source: type, values: dict[Any, Any]) -> dict[str, Any]:
    """Normalize and validate a partial update payload for a model.

    Update payloads are partial, so required fields not included in ``values``
    are not checked. Included fields use the same field validation and
    conversion rules as model construction and attribute assignment.
    """
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(key, Path):
            parts = key.parts
        elif isinstance(key, str):
            parts = tuple(key.split("."))
        else:
            parts = (str(key),)
        normalized[".".join(parts)] = value

    meta = getattr(source, "__db_metadata__", None)
    if meta and meta.timestamps and "updated_at" not in normalized:
        normalized["updated_at"] = datetime.now(timezone.utc)

    field_infos = getattr(source, "_model_fields", None)
    if not field_infos:
        return normalized

    validated: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}
    for path, value in normalized.items():
        parts = tuple(path.split("."))
        field_info = field_infos.get(parts[0])
        if field_info is None:
            errors[path] = [f"Unknown field '{parts[0]}'"]
            continue

        if len(parts) == 1:
            cleaned_value, field_errors = field_info.clean_and_validate(value, source)
            if field_errors:
                errors[path] = field_errors
            else:
                validated[path] = cleaned_value
            continue

        nested_model = field_info.model_cls if field_info.is_model else None
        nested_field = None
        for part in parts[1:]:
            if nested_model is None:
                break
            nested_field = nested_model._model_fields.get(part)
            if nested_field is None:
                break
            if nested_field.is_model:
                nested_model = nested_field.model_cls
            else:
                nested_model = None

        if nested_field is not None and nested_field.name == parts[-1]:
            cleaned_value, field_errors = nested_field.clean_and_validate(
                value, nested_model if nested_model is not None else field_info.model_cls
            )
            if field_errors:
                errors[path] = field_errors
            else:
                validated[path] = cleaned_value
            continue

        root_meta = meta.fields.get(parts[0]) if meta else None
        if root_meta is not None and root_meta.storage_type in (dict, list):
            validated[path] = value
            continue

        errors[path] = [f"Unknown nested field '{path}'"]

    if errors:
        raise ValidationError(errors)
    return validated
