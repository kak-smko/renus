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
    normalized = normalize_values(values)
    meta = getattr(source, "__db_metadata__", None)
    if meta and meta.timestamps and "updated_at" not in normalized:
        normalized["updated_at"] = datetime.now(timezone.utc)

    field_infos = getattr(source, "_model_fields", None)
    if not field_infos:
        return normalized

    validated: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}
    for name, value in normalized.items():
        field_info = field_infos.get(name)
        if field_info is not None:
            cleaned_value, field_errors = field_info.clean_and_validate(value, source)
            if field_errors:
                errors[name] = field_errors
            else:
                validated[name] = cleaned_value
            continue


        errors[name] = [f"Unknown field '{name}'"]

    if errors:
        raise ValidationError(errors)
    return validated
