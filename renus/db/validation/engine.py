from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from renus.response import Status, abort_if

if TYPE_CHECKING:
    from renus.db.models.base import Model


class Validate(dict[str, Any]):
    """Validate form data and return a dictionary of allowed fields.

    The model-based form validates only fields explicitly listed in ``fields``
    and present in ``form``.
    """

    def __init__(
        self,
        model: type[Model],
        form: dict[str, Any],
        fields: Iterable[str] | None = None
    ) -> None:
        super().__init__()

        form=dict(form)
        if fields is None:
            fields = model._model_fields.keys()

        selected_fields = [fields] if isinstance(fields, str) else list(fields)
        for name in selected_fields:
            abort_if(not isinstance(name, str) ,
            {"msg":"invalid_data","errors":{name:["fields must contain only field names as strings"]}},Status.HTTP_406_NOT_ACCEPTABLE)
        model_cls = model
        model_fields = model_cls._model_fields
        invalid_fields = [name for name in selected_fields if name not in model_fields]
       
        abort_if(invalid_fields ,
            {"msg":"invalid_data","errors":{"Unknown":[f"Unknown model field(s): {', '.join(invalid_fields)}"]}},Status.HTTP_406_NOT_ACCEPTABLE)
        
        source = copy.deepcopy(form)
        values: dict[str, Any] = {}
        errors: dict[str, list[Any]] = {}
        for name in selected_fields:
            if name not in source:
                continue

            value, field_errors = model_fields[name].clean_and_validate(source[name], model_cls)
            if field_errors:
                errors[name] = field_errors
            else:
                values[name] = value


        abort_if(errors,{"msg":"invalid_data","errors":errors},Status.HTTP_406_NOT_ACCEPTABLE)

        super().update(values)
        self._form = source

    