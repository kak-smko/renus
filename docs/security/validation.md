# Validation

Validation turns untrusted input into data that satisfies the rules your application expects. Renus provides two validation styles:

- `Model` and `Field` validation for structured application data.
- `Validate` with callable rules for dictionaries, forms, and nested input.

Validation is not authorization. A value can have the correct type and format but still be disallowed for the current user or operation.

## Model validation

Declare the accepted shape on a model. Fields without a default are required unless their annotation allows `None`:

```python
from renus.db import Field, Model
from renus.db.validation.rules import Email, In, MaxLen, MinLen, Regex


class Registration(Model):
    username: str = Field(MinLen(3), MaxLen(30), Regex(r"[a-z0-9_]+"))
    email: str = Field(Email())
    role: str = Field(In("user", "editor"))
```

Constructing the model validates its values. `Model.validate` accepts either a dictionary or a JSON string/bytes value:

```python
from renus.db import ValidationError

payload = {
    "username": "ada",
    "email": "ada@example.com",
    "role": "user",
}

try:
    registration = Registration.validate(payload)
except ValidationError as error:
    # error.errors maps field names to lists of messages.
    print(error.errors)
```

Invalid JSON raises `ValidationError`. A non-dictionary value also raises `ValidationError`.

For a complete reference to `Model`, `Field`, defaults, conversion, nested models, and field rules, see [`/docs/database/fields.md`](/docs/database/fields.md).

## Rules for dictionaries and forms

Use `Validate(data).rules(...)` when the input is not represented by a model:

```python
from renus.db.validation import Validate
from renus.db.validation.rules import Email, MaxLen, MinLen, Required


form = {
    "email": "ada@example.com",
    "display_name": "Ada",
}

result = Validate(form).rules({
    "email": [Required, Email()],
    "display_name": [Required, MinLen(2), MaxLen(80)],
})
```

The rule keys can use dot notation for nested dictionaries:

```python
result = Validate({"profile": {"age": 36}}).rules({
    "profile.age": [Required],
})
```

`rules()` returns only validated fields, preserving their nested structure. If any rule fails, it raises an HTTP validation error with status `422`; it does not return a partial result. Set `break_on_error=True` to stop at the first failing field, or `log_on_error=True` to log the collected errors before raising.

## Built-in rule groups

Rules are imported from `renus.db.validation.rules`:

| Group | Rules |
| --- | --- |
| Types | `String`, `Bool`, `List`, `Dict`, `Int`, `Float` |
| Values and lengths | `Len`, `MinLen`, `MaxLen`, `Eq`, `Min`, `Max`, `In`, `NotIn`, `Numeric`, `Accepted` |
| Formats | `Email`, `Regex`, `Url`, `Ip` |
| Files and records | `Extension`, `FileSize`, `Unique`, `Exists`, `ExistsCount` |
| Collections and structure | `Each`, `MaxDepth`, `Schema`, `Or`, `And` |
| Input processing | `Required`, `Default`, `Convert` |

Most rules treat `None` as valid; use `Required` when absence must be rejected. `Schema` can reject unknown keys when created with its default `strict=True`:

```python
from renus.db.validation.rules import Each, MaxLen, MinLen, Schema, String

profile_rule = Schema({
    "name": [MinLen(2), MaxLen(80)],
    "tags": [Each(String)],
})
```

Use `MaxDepth` and input-size limits when accepting deeply nested or attacker-controlled structures. Request body, header, cookie, and query limits are described in [`/docs/development/request.md`](/docs/development/request.md).

## Combining and writing rules

Rules are callable. A custom rule returns `True` for success, `False` for a generic failure, or a Renus error tuple such as `['custom_error', [value]]`:

```python
from renus.db import Field, Model


def positive(value):
    if value is None or value > 0:
        return True
    return ["positive_error", [value]]


class Invoice(Model):
    total: float = Field(positive)
```

Use `And(rule_a, rule_b)` when every rule must pass and `Or(rule_a, rule_b)` when at least one must pass. Use `Convert` before later rules when input needs normalization or type conversion.

## Security checklist

- Validate every client-controlled boundary, including JSON, forms, query values, headers, and uploaded-file metadata.
- Enforce business authorization separately from validation.
- Use allowlists such as `In`, `Regex`, `Extension`, and strict `Schema` where the accepted set is known.
- Add `MaxLen`, `FileSize`, and `MaxDepth` limits for untrusted input.
- Do not use validation as HTML escaping. Request form sanitization is covered in [`/docs/security/xss.md`](/docs/security/xss.md).
- Do not log raw credentials or tokens. For model field masking, see the sensitive-field section in [`/docs/database/fields.md`](/docs/database/fields.md).
