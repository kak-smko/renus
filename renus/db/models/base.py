from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from typing import Any, ClassVar

from renus.db.core.exceptions import ValidationError
from renus.db.core.state import IdentityKind, Lifecycle
from renus.db.metadata.core import (
    FieldMetadata,
    IdentityMetadata,
    Index,
    ModelMetadata,
    RelationshipMetadata,
)
from renus.db.metadata.inference import analyze_field_type, infer_identity_kind, is_optional_type
from renus.db.models.db_field import UNSET, DatabaseField
from renus.db.models.field import Field, FieldInfo, _UNSET
from renus.db.validation.base import Rule
from renus.datastructures.id import ID
from renus.db.query.ast import Path
from renus.db.relationships import EmbeddedMany, EmbeddedOne, Relationship


_MODEL_REGISTRY: dict[str, type] = {}

def _mapping_value_kind(annotation: Any) -> str | None:
    try:
        _nullable, base = is_optional_type(annotation)
    except Exception:
        return None
    if base is dict:
        return "Embedded"
    if base is list:
        return "EmbeddedMany"
    if isinstance(base, str):
        stripped = base.strip().lower()
        if stripped == "dict":
            return "Embedded"
        if stripped == "list":
            return "EmbeddedMany"
    return None

class ModelMeta(type):
    """Metaclass that builds model metadata and field definitions."""

    def __new__(mcls, name: str, bases: tuple[type, ...], ns: dict[str, Any]) -> Any:
        """Create and prepare a new model class.

        Parameters
        ----------
        name:
            Name of the class being created.
        bases:
            Tuple of base classes of the new class.
        ns:
            Class namespace dict containing the declared attributes.
        """

        declared_relationships: dict[str, Relationship] = {}
        declared_db_fields: dict[str, DatabaseField] = {}

        for key, val in list(ns.items()):
            if isinstance(val, Relationship):
                declared_relationships[key] = val

                ns[key] = Field(default=None if not val.is_collection else [])
            elif isinstance(val, DatabaseField):
                declared_db_fields[key] = val
                default_val = None if val.generated or val.primary_key else _UNSET
                ns[key] = Field(default=default_val, database=val)
            elif isinstance(val, Field):
                extra = getattr(val, "extra", {}) or {}
                db = getattr(val, "database", None) or extra.get("database") or extra.get("db")
                if isinstance(db, DatabaseField):
                    declared_db_fields[key] = db



        meta_cls = ns.get("Meta")
        timestamps = bool(getattr(meta_cls, "timestamps", False))
        soft_delete = bool(getattr(meta_cls, "soft_delete", False))

        annotations = dict(ns.get("__annotations__", {}))

        if timestamps:
            if "created_at" not in annotations:
                annotations["created_at"] = datetime | None
                ns["created_at"] = Field(default=None)
            if "updated_at" not in annotations:
                annotations["updated_at"] = datetime | None
                ns["updated_at"] = Field(default=None)

        if soft_delete:
            if "deleted_at" not in annotations:
                annotations["deleted_at"] = datetime | None
                ns["deleted_at"] = Field(default=None)
            if "is_deleted" not in annotations:
                annotations["is_deleted"] = bool
                ns["is_deleted"] = Field(default=False)

        ns["__annotations__"] = annotations

        cls = super().__new__(mcls, name, bases, ns)

        if name == "Model" and not bases:
            return cls

        table = getattr(meta_cls, "table", None)
        if not table:

            table = f"{name.lower()}s"

        all_relationships: dict[str, Relationship] = {}
        for base in reversed(cls.__mro__):
            for k, v in getattr(base, "__dict__", {}).items():
                if isinstance(v, Relationship):
                    all_relationships[k] = v
        all_relationships.update(declared_relationships)

        for fname, field_type in list(annotations.items()):
            if fname.startswith("_") or fname in all_relationships:
                continue
            rel_kind = _mapping_value_kind(field_type)
            if rel_kind is None:
                continue

            rel = (
                EmbeddedOne(dict)
                if rel_kind == "Embedded"
                else EmbeddedMany(list)
            )
            all_relationships[fname] = rel
            declared_relationships[fname] = rel

            ns[fname] = Field(default=None if not rel.is_collection else [])

        validation_fields: dict[str, FieldInfo] = getattr(cls, "_model_fields", {})
        for rname, rel in all_relationships.items():
            rel.__set_name__(cls, rname)
            setattr(cls, rname, rel)
            target = rel.target
            field_type = (
                list[target]
                if rel.is_collection
                and isinstance(target, type)
                and target not in (list, dict)
                else (list if rel.is_collection else target)
            )
            default = None if not rel.is_collection else []
            validation_fields[rname] = FieldInfo(
                name=rname,
                field_type=field_type,
                field=Field(*rel.rules, default=default, **rel.extra),
                default=default,
                model_base=Model,
            )

        if "_id" in annotations or "_id" in declared_db_fields:
            _id_type = annotations.get("_id", ID)
            _id_db = declared_db_fields.get("_id") or DatabaseField(primary_key=True)
            _id_field = Field(default=None, default_factory=ID, database=_id_db)
            validation_fields["_id"] = FieldInfo(
                name="_id",
                field_type=_id_type,
                field=_id_field,
                default=None,
                model_base=Model,
            )

        if soft_delete and "is_deleted" in cls.__dict__:
            delattr(cls, "is_deleted")

        fields_dict: dict[str, FieldMetadata] = {}
        column_to_field: dict[str, str] = {}

        for fname, fi in list(validation_fields.items()):
            if soft_delete and fname == "is_deleted":
                continue
            if (fname.startswith("_") and fname != "_id") or fname in all_relationships:
                continue

            raw_field = getattr(fi, "field", None)
            extra = getattr(raw_field, "extra", {}) or {}
            sensitive = bool(getattr(raw_field, "sensitive", False))
            db = (
                getattr(raw_field, "database", None)
                or extra.get("database")
                or extra.get("db")
                or declared_db_fields.get(fname)
            )
            if not isinstance(db, DatabaseField):
                db = DatabaseField()

            is_nullable, base_type, storage_type = analyze_field_type(fi.field_type)

            effective_nullable = is_nullable
            effective_storage_type = storage_type
            col_name = db.column_name or fname

            pk = db.primary_key or (fname in ("id", "_id") and not any(
                d.primary_key for d in declared_db_fields.values()
            ))

            if db.auto_inc and not pk:
                raise ValueError(
                    f"Field '{fname}' with auto_inc=True must be primary_key=True"
                )

            identity_kind: IdentityKind | None = None
            if pk:
                if db.identity_kind is not None:
                    identity_kind = (
                        IdentityKind(db.identity_kind)
                        if isinstance(db.identity_kind, str)
                        else db.identity_kind
                    )
                else:
                    identity_kind = infer_identity_kind(
                        fname, fi.field_type, effective_storage_type, db.generated
                    )

            def_val = fi.get_default() if fi.has_default else UNSET
            def_factory = raw_field.default_factory if raw_field else None

            if pk or db.generated:
                fi.required = False

            field_meta = FieldMetadata(
                name=fname,
                column_name=col_name,
                python_type=fi.field_type,
                inferred_type=base_type,
                storage_type=effective_storage_type,
                nullable=effective_nullable,
                required=getattr(fi, "required", False),
                database=db,
                validation=raw_field,
                primary_key=pk,
                identity_kind=identity_kind,
                generated=db.generated,
                unique=db.unique,
                indexed=db.indexed or db.unique,
                index_name=db.index_name,
                default=def_val,
                default_factory=def_factory,
                foreign_key=db.foreign_key,
                on_delete=db.on_delete,
                on_update=db.on_update,
                immutable=db.immutable,
                comment=db.comment,
                sensitive=sensitive,
            )

            fields_dict[fname] = field_meta
            column_to_field[col_name] = fname

            if fname not in {
                "state",
                "is_new",
                "is_persisted",
                "is_dirty",
                "is_deleted",
                "dirty_fields",
                "identity_values",
                "identity_dict",
            }:
                setattr(cls, fname, Path(cls, (fname,)))

        if soft_delete and "is_deleted" not in fields_dict:
            fields_dict["is_deleted"] = FieldMetadata(
                name="is_deleted",
                column_name="is_deleted",
                python_type=bool,
                inferred_type=bool,
                storage_type=bool,
                nullable=False,
                required=False,
                database=DatabaseField(),
                default=False,
            )
            column_to_field["is_deleted"] = "is_deleted"

        pk_fields = [k for k, v in fields_dict.items() if v.primary_key]
        if len(pk_fields) > 1:
            identity = IdentityMetadata(
                fields=tuple(pk_fields),
                kind=IdentityKind.COMPOSITE,
                generated=False,
            )
        elif len(pk_fields) == 1:
            pk_name = pk_fields[0]
            pk_meta = fields_dict[pk_name]
            identity = IdentityMetadata(
                fields=(pk_name,),
                kind=pk_meta.identity_kind or IdentityKind.INTEGER,
                generated=pk_meta.generated,
            )
        else:

            if "_id" in fields_dict:
                pk_meta = fields_dict["_id"]
                object.__setattr__(pk_meta, "primary_key", True)
                identity = IdentityMetadata(
                    fields=("_id",),
                    kind=IdentityKind.ID,
                    generated=True,
                )
            elif "id" in fields_dict:
                pk_meta = fields_dict["id"]
                object.__setattr__(pk_meta, "primary_key", True)
                kind = pk_meta.identity_kind or infer_identity_kind(
                    "id", pk_meta.python_type, pk_meta.storage_type, pk_meta.generated
                )
                identity = IdentityMetadata(
                    fields=("id",),
                    kind=kind,
                    generated=pk_meta.generated,
                )
            else:

                default_db = DatabaseField(primary_key=True, generated=True)
                id_meta = FieldMetadata(
                    name="id",
                    column_name="id",
                    python_type=int,
                    inferred_type=int,
                    storage_type=int,
                    nullable=False,
                    required=False,
                    database=default_db,
                    primary_key=True,
                    identity_kind=IdentityKind.INTEGER,
                    generated=True,
                )
                fields_dict["id"] = id_meta
                column_to_field["id"] = "id"
                validation_fields["id"] = FieldInfo(
                    name="id",
                    field_type=int,
                    field=Field(default=None),
                    default=None,
                    model_base=Model,
                )
                identity = IdentityMetadata(
                    fields=("id",),
                    kind=IdentityKind.INTEGER,
                    generated=True,
                )
                setattr(cls, "id", Path(cls, ("id",)))

        rel_metadata: dict[str, RelationshipMetadata] = {}
        for rname, rel in all_relationships.items():
            rel_meta = RelationshipMetadata(
                name=rname,
                kind=rel.kind,
                target=rel.target,
                local_key=rel.local_key,
                foreign_key=rel.foreign_key,
                through=rel.through,
                on_save=rel.on_save,
                on_delete=rel.on_delete,
                on_update=rel.on_update,
                loading=rel.loading,
                is_embedded=rel.is_embedded,
                is_collection=rel.is_collection,
            )
            rel_metadata[rname] = rel_meta

        indexes: list[Index] = []

        for fname, fmeta in fields_dict.items():
            if fmeta.unique:
                indexes.append(Index(fmeta.column_name, unique=True, name=fmeta.index_name))
            elif fmeta.indexed:
                indexes.append(Index(fmeta.column_name, unique=False, name=fmeta.index_name))

        meta_indexes = getattr(meta_cls, "indexes", ())
        if isinstance(meta_indexes, (list, tuple)):
            for idx in meta_indexes:
                if isinstance(idx, Index):
                    indexes.append(idx)


        model_meta = ModelMetadata(
            model=cls,
            table=table,
            fields=fields_dict,
            column_to_field=column_to_field,
            identity=identity,
            relationships=rel_metadata,
            indexes=tuple(indexes),
            timestamps=timestamps,
            soft_delete=soft_delete,
            created_at_field="created_at" if timestamps else None,
            updated_at_field="updated_at" if timestamps else None,
            deleted_at_field="deleted_at" if soft_delete else None,
            is_deleted_field="is_deleted" if soft_delete else None,
        )
        setattr(cls, "__db_metadata__", model_meta)
        _MODEL_REGISTRY[name] = cls

        return cls

class Model(metaclass=ModelMeta):
    """Base class for declarative database models."""

    _is_model_class = True
    _model_fields: ClassVar[dict[str, FieldInfo]] = {}

    __db_metadata__: ClassVar[ModelMetadata]
    _db_state: Lifecycle
    _db_original_snapshot: dict[str, Any]

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._setup_model_fields()

    @classmethod
    def _setup_model_fields(cls) -> None:
        fields: dict[str, FieldInfo] = {}

        all_annotations: dict[str, Any] = {}
        for base in reversed(cls.__mro__):
            if hasattr(base, "__annotations__"):
                all_annotations.update(base.__annotations__)

        for name, field_type in all_annotations.items():
            if name.startswith("_"):
                continue

            val = cls.__dict__.get(name, _UNSET)
            if isinstance(val, Field):
                field_obj = val
                default_val = val.default
            elif val is not _UNSET:
                field_obj = Field(default=val)
                default_val = val
            else:
                field_obj = Field()
                default_val = _UNSET

            fields[name] = FieldInfo(
                name=name,
                field_type=field_type,
                field=field_obj,
                default=default_val,
                model_base=Model,
            )

        cls._model_fields = fields


    @classmethod
    def schema(cls) -> dict[str, Any]:
        """Return a JSON Schema for the model.

        The schema is derived from the model's annotations, validation rules,
        and relationship metadata. Nested model fields and relationships are
        represented recursively, including relationships declared without an
        annotation such as ``items = EmbeddedMany(Item)``.

        The returned dictionary is JSON-serializable and follows the JSON
        Schema vocabulary. Models that contain recursive relationships use
        ``$defs`` and ``$ref`` to avoid infinite schemas.
        """
        referenced: set[type] = set()
        definitions: dict[str, dict[str, Any]] = {}

        def definition_name(model: type) -> str:
            return model.__name__

        def json_value(value: Any) -> Any:
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, ID):
                return json_value(value.value)
            if isinstance(value, Model):
                return {key: json_value(item) for key, item in dict(value).items()}
            if isinstance(value, list):
                return [json_value(item) for item in value]
            if isinstance(value, tuple):
                return [json_value(item) for item in value]
            if isinstance(value, dict):
                return {str(key): json_value(item) for key, item in value.items()}
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            return None

        def add_nullable(value_schema: dict[str, Any]) -> dict[str, Any]:
            if not value_schema or value_schema.get("type") == "null":
                return value_schema
            result = dict(value_schema)
            value_type = result.get("type")
            if isinstance(value_type, str):
                result["type"] = [value_type, "null"]
            else:
                result = {"anyOf": [value_schema, {"type": "null"}]}
            return result

        def rule_schema(field_info: FieldInfo) -> dict[str, Any]:
            """Collect schema fragments explicitly supplied by validation rules.

            Every validation rule is a ``Rule`` and provides its own JSON
            Schema fragment through ``json_schema()``.
            """
            result: dict[str, Any] = {}
            for rule in field_info.field.rules:
                if not isinstance(rule, Rule):
                    raise TypeError("Validation rules must inherit Rule")
                fragment = rule.json_schema()
                if not isinstance(fragment, dict):
                    raise TypeError(
                        f"{type(rule).__name__}.json_schema() must return a dict"
                    )
                result.update(fragment)
            return result

        def type_schema(field_info: FieldInfo, stack: set[type]) -> dict[str, Any]:
            if field_info.is_model and field_info.model_cls is not None:
                return model_schema(field_info.model_cls, stack)
            if field_info.is_model_list and field_info.model_cls is not None:
                return {
                    "type": "array",
                    "items": model_schema(field_info.model_cls, stack),
                }

            type_names: list[str] = []
            formats: list[str] = []
            for field_type in field_info.effective_types:
                if field_type is str:
                    type_name = "string"
                elif field_type is int:
                    type_name = "integer"
                elif field_type is float:
                    type_name = "number"
                elif field_type is bool:
                    type_name = "boolean"
                elif field_type is list:
                    type_name = "array"
                elif field_type is dict:
                    type_name = "object"
                elif field_type is date:
                    type_name = "string"
                    formats.append("date")
                elif field_type is datetime:
                    type_name = "string"
                    formats.append("date-time")
                elif field_type is ID:
                    type_name = "string"
                elif field_type in (Any, object):
                    continue
                else:

                    # Custom runtime types need an explicit schema rule or a
                    # custom Model schema implementation.
                    continue
                if type_name not in type_names:
                    type_names.append(type_name)

            if not type_names:
                result: dict[str, Any] = {}
            elif type_names == ["integer|string"]:
                result = {"type": ["integer", "string"]}
            elif len(type_names) == 1:
                result = {"type": type_names[0]}
            else:
                result = {"type": type_names}
            if formats and result.get("type") == "string":
                result["format"] = formats[0]
            return result

        def field_schema(field_info: FieldInfo, stack: set[type]) -> dict[str, Any]:
            result = type_schema(field_info, stack)
            result.update(rule_schema(field_info))
            if field_info.field.description:
                result["description"] = field_info.field.description
            if field_info.has_default and field_info.field.default is not _UNSET:
                result["default"] = json_value(field_info.field.default)
            if field_info.is_nullable:
                result = add_nullable(result)
            return result

        def relationship_schema(rel: RelationshipMetadata, stack: set[type]) -> dict[str, Any]:
            target = rel.target
            if target is dict:
                result: dict[str, Any] = {"type": "object"}
            elif target is list:
                result = {"type": "array", "items": {}}
            elif isinstance(target, type) and issubclass(target, Model):
                result = model_schema(target, stack)
            else:
                result = {}

            if rel.is_collection:
                if result.get("type") != "array":
                    result = {"type": "array", "items": result}
            else:
                result = add_nullable(result)
            return result

        def model_schema(model: type, stack: set[type]) -> dict[str, Any]:
            if model in stack:
                referenced.add(model)
                return {"$ref": f"#/$defs/{definition_name(model)}"}

            next_stack = set(stack)
            next_stack.add(model)
            metadata = model.metadata()
            relationships = metadata.relationships
            properties: dict[str, Any] = {}
            required: list[str] = []

            for name, field_info in model._model_fields.items():
                if name in relationships:
                    continue
                properties[name] = field_schema(field_info, next_stack)
                if field_info.required or any(
                    getattr(rule, "is_required", False)
                    for rule in field_info.field.rules
                ):
                    required.append(name)

            for name, relationship in relationships.items():
                properties[name] = relationship_schema(relationship, next_stack)

            result: dict[str, Any] = {
                "title": model.__name__,
                "type": "object",
                "properties": properties,
                "additionalProperties": True,
            }
            if required:
                result["required"] = required
            return result

        result = model_schema(cls, set())
        pending = list(referenced)
        while pending:
            model = pending.pop()
            name = definition_name(model)
            if name in definitions:
                continue
            before = set(referenced)
            definitions[name] = model_schema(model, {model})
            pending.extend(referenced - before)

        if definitions:
            result["$defs"] = definitions
        result["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        return result

    @staticmethod
    def _is_model_type(field_type: Any) -> bool:
        return bool(field_type) and isinstance(field_type, type) and issubclass(field_type, Model)

    @classmethod
    def _dump_value(cls, val: Any) -> Any:
        if isinstance(val, Model):
            return dict(val)
        elif isinstance(val, list):
            return [cls._dump_value(item) for item in val]
        elif isinstance(val, tuple):
            return tuple(cls._dump_value(item) for item in val)
        elif isinstance(val, dict):
            return {k: cls._dump_value(v) for k, v in val.items()}
        return val

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a plain dictionary."""
        return dict(self)

    def dict(self) -> dict[str, Any]:
        """Return the model as a plain dictionary."""
        return dict(self)

    def get_sensitive(self, name: str) -> Any:
        """Return a field's raw value, bypassing sensitive masking."""
        if name == "is_deleted":
            return self.__dict__.get("_is_deleted_value", False)
        return object.__getattribute__(self, name)

    def __getattribute__(self, name: str) -> Any:
        obj_ga = object.__getattribute__
        if name.startswith("__") and name.endswith("__"):
            return obj_ga(self, name)
        try:
            meta = obj_ga(self, "__db_metadata__")
        except AttributeError:
            return obj_ga(self, name)
        if meta is not None:
            fmeta = meta.fields.get(name)
            if fmeta is not None and fmeta.sensitive:
                val = obj_ga(self, name)
                return "***" if val is not None else None
        return obj_ga(self, name)

    def __iter__(self):
        keys = list(self._model_fields.keys())
        for k in self.__dict__:
            if (not k.startswith("_") and k not in keys) or (k == "_id" and k not in keys):
                keys.append(k)

        meta = self.__db_metadata__
        for key in keys:
            field_meta = meta.fields.get(key) if meta is not None else None
            if field_meta is not None and field_meta.sensitive:
                continue
            val = self.get_sensitive(key)
            yield (key, self._dump_value(val))

    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item)

    def __setitem__(self, item: str, value: Any) -> None:
        setattr(self, item, value)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)

    def __repr__(self) -> str:
        meta = self.__db_metadata__
        attrs_list = []
        for key in self._model_fields:
            value = self.get_sensitive(key)
            field_meta = meta.fields.get(key) if meta is not None else None
            if field_meta is not None and field_meta.sensitive:
                value = "***" if value is not None else None
            else:
                value = self._dump_value(value)
            attrs_list.append(f"{key}={value!r}")
        return f"{self.__class__.__name__}({', '.join(attrs_list)})"

    def __str__(self) -> str:
        return self.__repr__()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Model):
            return dict(self) == dict(other)
        if isinstance(other, dict):
            return dict(self) == other
        return False

    def __init__(self, doc: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Populate and validate a new model instance.

        Parameters
        ----------
        doc:
            Optional mapping of field names to values used to populate the model.
        **kwargs:
            Additional field values passed as keyword arguments.
        """

        object.__setattr__(self, "_db_state", Lifecycle.NEW)
        object.__setattr__(self, "_db_original_snapshot", {})

        meta = getattr(self.__class__, "__db_metadata__", None)

        try:

            object.__setattr__(self, "_initialized", False)

            if not self._model_fields and getattr(self.__class__, "__annotations__", None):
                self.__class__._setup_model_fields()

            data: dict[str, Any] = {}
            if doc is not None:
                if isinstance(doc, dict):
                    data.update(doc)
                elif not kwargs:
                    raise ValidationError(
                        f"Expected dict or keyword arguments, got {type(doc).__name__}"
                    )
            if kwargs:
                data.update(kwargs)

            errors: dict[str, list[str]] = {}
            values: dict[str, Any] = {}

            for name, field_info in self._model_fields.items():
                raw_val = data.get(name, _UNSET)

                if raw_val is _UNSET:
                    if field_info.has_default:
                        val = field_info.get_default()
                    elif field_info.is_nullable:
                        val = None
                    else:
                        if field_info.required:
                            errors[name] = [f"'{name}' is required"]
                            continue
                        val = None
                else:
                    val = raw_val

                cleaned_val, field_errors = field_info.clean_and_validate(val, self.__class__)
                if field_errors:
                    errors[name] = field_errors
                else:
                    values[name] = cleaned_val

            relationship_names = set(meta.relationships.keys()) if meta else set()
            for key, val in data.items():
                if key not in self._model_fields and key not in relationship_names:
                    # Mass-assignment guard: input dicts (e.g. request bodies,
                    # untrusted JSON via from_dict) may only set declared
                    # fields; relationship keys are allowed so row hydration
                    # can carry eagerly loaded data onto the instance.
                    errors[key] = [f"Unknown field '{key}'"]
                    continue
                if key not in self._model_fields:
                    values[key] = val

            if errors:
                raise ValidationError(errors)

            for key, val in values.items():
                if key == "is_deleted":
                    object.__setattr__(self, "_is_deleted_value", val)
                else:
                    object.__setattr__(self, key, val)

            object.__setattr__(self, "_initialized", True)
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError(e.args or str(e)) from e


        if meta and meta.timestamps:
            now = datetime.now(timezone.utc)
            if getattr(self, "created_at", None) is None:
                object.__setattr__(self, "created_at", now)
            if getattr(self, "updated_at", None) is None:
                object.__setattr__(self, "updated_at", now)

        if meta and meta.soft_delete:
            if "_is_deleted_value" not in self.__dict__:
                object.__setattr__(self, "_is_deleted_value", False)

        object.__setattr__(self, "_db_original_snapshot", self._take_field_snapshot())

    def _take_field_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        meta = getattr(self, "__db_metadata__", None)
        if meta:
            for fname in meta.fields:
                if fname == "is_deleted":
                    val = self.__dict__.get("_is_deleted_value", False)
                elif fname in self.__dict__:
                    val = self.__dict__[fname]
                else:
                    continue
                try:
                    snapshot[fname] = copy.deepcopy(val)
                except Exception:
                    snapshot[fname] = val
        return snapshot

    def __setattr__(self, name: str, value: Any) -> None:

        if name == "is_deleted":
            object.__setattr__(self, "_is_deleted_value", value)
            if getattr(self, "_initialized", False):
                object.__setattr__(self, "_db_state", Lifecycle.DIRTY)
            return

        if getattr(self, "_initialized", False) and hasattr(self, "__db_metadata__"):
            meta = self.__db_metadata__
            fmeta = meta.fields.get(name)

            if (
                fmeta
                and fmeta.immutable
                and getattr(self, "_db_state", Lifecycle.NEW)
                in (Lifecycle.PERSISTED, Lifecycle.DIRTY)
            ):
                original_val = self._db_original_snapshot.get(name)
                if original_val is not None and original_val != value:
                    raise ValidationError(
                        {name: [f"Field '{name}' is immutable and cannot be modified."]}
                    )

            try:
                if name in self._model_fields:
                    field_info = self._model_fields[name]
                    cleaned_val, field_errors = field_info.clean_and_validate(value, self.__class__)
                    if field_errors:
                        raise ValidationError({name: field_errors})
                    if name == "is_deleted":
                        object.__setattr__(self, "_is_deleted_value", cleaned_val)
                    else:
                        object.__setattr__(self, name, cleaned_val)
                else:
                    object.__setattr__(self, name, value)
            except Exception as e:
                if isinstance(e, ValidationError):
                    raise
                raise ValidationError(e.args or str(e)) from e

            is_relationship = name in meta.relationships
            current_state = getattr(self, "_db_state", Lifecycle.NEW)
            if (fmeta or is_relationship) and current_state in (
                Lifecycle.PERSISTED,
                Lifecycle.DIRTY,
            ):
                if is_relationship or self._is_field_dirty(name):
                    object.__setattr__(self, "_db_state", Lifecycle.DIRTY)
                else:

                    if not self._any_field_dirty():
                        object.__setattr__(self, "_db_state", Lifecycle.PERSISTED)
        else:
            object.__setattr__(self, name, value)

    def _is_field_dirty(self, name: str) -> bool:
        current = self.get_sensitive(name) if name == "is_deleted" else self.__dict__.get(name)
        original = self._db_original_snapshot.get(name)
        return current != original

    def _any_field_dirty(self) -> bool:
        meta = self.__db_metadata__
        for fname in meta.fields:
            if self._is_field_dirty(fname):
                return True
        return False

    def state(self) -> Lifecycle:
        """Return the model's current lifecycle state."""
        return getattr(self, "_db_state", Lifecycle.NEW)

    def is_new(self) -> bool:
        """Return whether the model has not yet been persisted."""
        return self.state() == Lifecycle.NEW

    def is_persisted(self) -> bool:
        """Return whether the model has been persisted and is clean."""
        return self.state() == Lifecycle.PERSISTED

    def is_dirty(self) -> bool:
        """Return whether any field differs from its persisted snapshot."""
        if self.state() == Lifecycle.DIRTY:
            return True
        if self.state() == Lifecycle.NEW:
            return False
        return self._any_field_dirty()

    def is_deleted(self) -> bool:
        """Return whether the model has been deleted."""
        if self.state() == Lifecycle.DELETED:
            return True
        if getattr(self, "deleted_at", None) is not None:
            return True
        return bool(self.__dict__.get("_is_deleted_value", False))

    def dirty_fields(self) -> set[str]:
        """Return the set of field names that have changed."""
        if self.state() == Lifecycle.NEW:
            return set(self.__db_metadata__.fields.keys()) & set(self.__dict__.keys())

        dirty: set[str] = set()
        for fname in self.__db_metadata__.fields:
            if self._is_field_dirty(fname):
                dirty.add(fname)
        return dirty

    def get_dirty_changes(self) -> dict[str, tuple[Any, Any]]:
        """Return changed fields mapped to their original and current values."""
        changes: dict[str, tuple[Any, Any]] = {}
        for fname in self.dirty_fields():
            original = self._db_original_snapshot.get(fname)
            current = self.get_sensitive(fname) if fname == "is_deleted" else self.__dict__.get(fname)
            changes[fname] = (original, current)
        return changes

    def _mark_persisted(self) -> None:
        object.__setattr__(self, "_db_state", Lifecycle.PERSISTED)
        object.__setattr__(self, "_db_original_snapshot", self._take_field_snapshot())

    def _mark_deleted(self) -> None:
        object.__setattr__(self, "_db_state", Lifecycle.DELETED)

    def _mark_detached(self) -> None:
        object.__setattr__(self, "_db_state", Lifecycle.DETACHED)

    def _mark_dirty(self) -> None:
        object.__setattr__(self, "_db_state", Lifecycle.DIRTY)

    def soft_delete(self) -> None:
        """Mark the model as softly deleted, if enabled on the model."""
        meta = self.__db_metadata__
        if not meta.soft_delete:
            raise ValueError(
                f"Model '{self.__class__.__name__}' does not have soft_delete enabled in Meta"
            )
        now = datetime.now(timezone.utc)
        object.__setattr__(self, "deleted_at", now)
        object.__setattr__(self, "_is_deleted_value", True)
        self._mark_deleted()

    def restore(self) -> None:
        """Restore a softly deleted model to an active dirty state."""
        meta = self.__db_metadata__
        if not meta.soft_delete:
            raise ValueError(
                f"Model '{self.__class__.__name__}' does not have soft_delete enabled in Meta"
            )
        object.__setattr__(self, "deleted_at", None)
        object.__setattr__(self, "_is_deleted_value", False)
        object.__setattr__(self, "_db_state", Lifecycle.DIRTY)

    def identity_values(self) -> Any:
        """Return the identity key value(s) for this model."""
        meta = self.__db_metadata__
        pk_fields = meta.identity.fields
        if len(pk_fields) == 1:
            return getattr(self, pk_fields[0], None)
        return tuple(getattr(self, f, None) for f in pk_fields)

    def identity_dict(self) -> dict[str, Any]:
        """Return the identity fields as a name-to-value dictionary."""
        meta = self.__db_metadata__
        return {f: getattr(self, f, None) for f in meta.identity.fields}


    @classmethod
    def metadata(cls) -> ModelMetadata:
        """Return the model's metadata object."""
        return cls.__db_metadata__

