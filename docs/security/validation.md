# Validation

Validation turns untrusted input into values that satisfy the types and constraints your application expects. Renus provides model-field validation and a helper for validating a selected subset of a model's fields. Validation is not authorization: a value can be well-formed and still be disallowed for the current user or operation.

## Model validation

Declare the accepted shape and constraints on a `Model`. A field without a default is required unless its annotation allows `None`:

```python
from renus.db import Field, Model
from renus.db.validation import Email, In, MaxLen, MinLen, Regex


class Registration(Model):
    username: str = Field(MinLen(3), MaxLen(30), Regex(r"[a-z0-9_]+"))
    email: str = Field(Email())
    role: str = Field(In("user", "editor"))
```

Creating a model validates its declared fields, including when values are passed as a dictionary. Unknown input keys are rejected:

```python
from renus.db import ValidationError

payload = {
    "username": "ada",
    "email": "ada@example.com",
    "role": "user",
}

try:
    registration = Registration(payload)
except ValidationError as error:
    # A mapping from field names to structured error codes and arguments.
    # Example: {"age": [["type_error", ["int", "str"]]]}
    print(error.errors)
```

Declared fields are validated again when assigned after initialization. See [`/docs/database/fields.md`](/docs/database/fields.md) for `Field`, defaults, conversion, nested models, and model JSON Schema.

## Validate selected model fields

`Validate` takes a model class, a dictionary of submitted values, and an optional iterable of allowed field names. It returns a `dict` containing only selected fields that were present in the input, after applying each field's normal cleaning and validation:

```python
from renus.db import Field, Model, ValidationError
from renus.db.validation import Email, MaxLen, MinLen, Validate


class Profile(Model):
    display_name: str = Field(MinLen(2), MaxLen(80))
    email: str = Field(Email())
    age: int

form = {
    "display_name": "Ada",
    "email": "ada@example.com",
    "age": "not validated because it is not selected",
    "is_admin": True,
}

try:
    values = Validate(Profile, form, fields=("display_name", "email"))
except ValidationError as error:
    print(error.errors)
else:
    # {"display_name": "Ada", "email": "ada@example.com"}
    save_profile_changes(values)
```

`Validate` is useful for allowlisted partial updates. The input must be a `dict`; it is deep-copied before field values are cleaned. Extra input keys are omitted. Fields absent from the input are also omitted rather than treated as required, so the helper does not construct a complete model or validate required-field presence. If `fields` is omitted, it selects all model fields; you can also pass a single field name as a string. An unknown selected field raises `ValueError`, a non-dictionary input raises `TypeError`, and invalid selected values raise `ValidationError` with errors grouped by field.


## Built-in rules

Import built-in rules from `renus.db.validation` (or from `renus.db.validation.rules`):

| Group | Rules |
| --- | --- |
| Types | `String`, `Bool`, `List`, `Dict`, `Int`, `Float` |
| Lengths and values | `Len`, `MinLen`, `MaxLen`, `Eq`, `Min`, `Max`, `In`, `NotIn`, `Numeric`, `Accepted` |
| Formats | `Email`, `Regex`, `Url`, `Ip` |
| Files and records | `Extension`, `FileSize`, `Unique`, `Exists`, `ExistsCount` |
| Collections and structure | `Each`, `MaxDepth` |
| Composition | `Or`, `And` |
| Presence | `Required` |

Examples:

```python
from renus.db import Field, Model
from renus.db.validation import Each, Email, Extension, MaxDepth, MaxLen, MinLen, String


class UploadForm(Model):
    attachments: list[str] = Field(Each(Extension(["png", "jpg", "pdf"])))
    tags: list[str] = Field(Each(String()), MaxLen(10))
    description: str = Field(MinLen(1), MaxLen(500))
    metadata: dict = Field(MaxDepth(4))
```

Most built-in rules accept `None`; model requiredness normally comes from the annotation and whether the field has a default. For optional/partial input, remember that `Validate` skips fields missing from the form.

`Each` applies its rules to every value in a list or dictionary. `Or` succeeds when any child rule succeeds; `And` requires all child rules to succeed. These composition rules accept `Rule` instances (and can also normalize `Rule` subclasses). The package does not currently provide a `Schema` rule for validating arbitrary nested dictionary shapes; use nested `Model` fields when you need a declared nested schema.

`Unique`, `Exists`, and `ExistsCount` are database-backed rules configured with a model/query interface and field name. `FileSize` checks file paths on disk. These checks can perform I/O and depend on the model/query and filesystem interfaces provided by the application; do not assume they are asynchronous or suitable for use directly with an async repository. Validate authorization and uploaded-file ownership separately.

## Custom rules

A validation rule inherits `Rule` and implements both `__call__()` and `json_schema()`. Import the base class from `renus.db.validation.base`:

```python
from typing import Any

from renus.db import Field, Model
from renus.db.validation.base import Rule


class PositiveNumber(Rule):
    def __call__(self, value: Any):
        if value is None or value > 0:
            return True
        return ["positive_error", [value]]

    def json_schema(self):
        return {"exclusiveMinimum": 0}


class Invoice(Model):
    total: float = Field(PositiveNumber())
```

A rule returns `True` for success. Returning `False` produces a generic validation error; built-in-style error results such as `["some_error", [value]]` are also supported. A rule may return a replacement value to normalize input, for example a stripped string. `json_schema()` must return a dictionary containing the rule's JSON Schema fragment, or `{}` when the rule has no schema representation. `Model.schema()` combines these fragments with the model's annotated types.

`Field` accepts `Rule` instances (and `Rule` subclasses, which it instantiates); plain functions and lambdas are not accepted as field rules. Keep custom rules deterministic and avoid hidden network or database calls where possible.

## Security checklist

- Validate every client-controlled boundary, including JSON, forms, query values, headers, and uploaded-file metadata.
- Use `Validate(Model, form, fields=...)` with an explicit field allowlist for partial updates; never mass-assign a raw request dictionary.
- Enforce business authorization separately from validation.
- Prefer allowlists such as `In`, constrained `Regex`, and `Extension` when the accepted set is known.
- Bound strings, collections, file sizes, nesting depth, and request-body size.
- Do not use validation as HTML escaping. Request form sanitization is covered in [`/docs/security/xss.md`](/docs/security/xss.md).
- Do not log raw credentials or tokens. For model field masking, see the sensitive-field section in [`/docs/database/fields.md`](/docs/database/fields.md).
