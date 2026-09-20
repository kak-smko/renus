# ID

`ID` is Renus's configurable identity value type. Use it when a model's primary key should follow the identity configured for the active database instead of being tied directly to `int`, `str`, `ObjectId`, or `UUID`.

`ID` lives in the `renus.datastructures` package:

```python
from renus.datastructures import ID
```

## 1. `ID` in one minute

A model can use `ID` as its primary-key type:

```python
from renus.datastructures import ID
from renus.db import DatabaseField, Field, Model


class Document(Model):
    _id: ID = Field(
        default_factory=ID,
        database=DatabaseField(primary_key=True),
    )
    title: str
```

Create a document without supplying `_id`:

```python
document = Document(title="Renus guide")

print(document._id)       # the configured identity value
print(str(document._id))  # text representation of the identity
```

`default_factory=ID` creates a separate identity for each model instance. The identity configuration is read from `config.database` through `Config("database")`.

## 2. `ID` versus `id`

These names have different roles:

| Name | Meaning |
| --- | --- |
| `ID` | Renus's configurable identity value object. |
| `id` or `_id` | A field on a model that stores an identity. |
| `primary_key=True` | Marks a field as part of the model identity. |

Renus automatically gives a model a generated integer `id` field when it declares no identity field. Use an explicit field when you need a different identity type or database behavior.

The `_id` spelling is useful when the database or document model convention uses `_id`. A field named `id` is also valid:

```python
from renus.datastructures import ID
from renus.db import DatabaseField, Field, Model


class User(Model):
    id: ID = Field(
        default_factory=ID,
        database=DatabaseField(
            primary_key=True,
            generated=True,
        ),
    )
    username: str
```

For the configured `ID` pattern, always make the field a primary key. Without `primary_key=True`, the field is an ordinary field rather than the model's identity.

## 3. Configure the identity type

Renus loads database settings from `config/database.py`. Set `ID` to the concrete identity class or factory that should be used:

```python
# config/database.py

ID = str
```

The supported built-in choices are:

| Configuration | New identity behavior |
| --- | --- |
| `int` | Returns `None` from `ID()` so the database adapter allocates the integer. |
| `str` | Generates a UUID-based hexadecimal string. |
| `UUID` | Generates a UUID with `uuid4()`. |
| A callable | Calls it to create the identity. ex: bson.ObjectId |

For example, configure UUID values:

```python
# config/database.py

from uuid import UUID

ID = UUID
```

Or configure a project-specific factory:

```python
# config/database.py

from secrets import token_urlsafe


def make_document_id() -> str:
    return token_urlsafe(24)


ID = make_document_id
```

The configured callable must return a value. If it returns `None`, Renus raises `ValueError` when it tries to create an identity.

If the configuration is missing, Renus uses `int` as the default identity configuration. Integer identities are allocated by the database adapter rather than minted by `ID` itself.

## 4. Create new and existing identities

Calling `ID()` creates a new identity according to the configuration:

```python
from renus.datastructures import ID

new_identity = ID()
```

Pass a value to wrap an existing identity:

```python
existing_identity = ID("507f1f77bcf86cd799439011")

print(str(existing_identity))
```

The value is coerced to the configured identity type. For example, with `ID = int`:

```python
# config/database.py
ID = int
```

```python
from renus.datastructures import ID

identity = ID("42")

assert identity.value == 42
assert identity == 42
```

Passing an existing `ID` unwraps and reuses its underlying value:

```python
first = ID("document-42")
second = ID(first)

assert second == first
```

Useful value-object behavior:

```python
identity = ID("document-42")

str(identity)       # "document-42"
repr(identity)      # ID('document-42')
bool(identity)      # based on the wrapped value
identity == "document-42"
hash(identity)      # hash of the wrapped value
```

## 5. Use `ID` in a model

A complete model using a generated configured identity looks like this:

```python
from renus.datastructures import ID
from renus.db import DatabaseField, Field, Model


class Document(Model):
    _id: ID = Field(
        default_factory=ID,
        database=DatabaseField(
            primary_key=True,
            generated=True,
        ),
    )
    title: str


document = Document(title="Identity basics")
print(document.identity_values())
print(document.identity_dict())
```

`identity_values()` returns the model's primary-key value. `identity_dict()` returns the primary-key field name and value:

```python
print(document.identity_dict())
# {"_id": ID(...)}
```

For a single primary key, `identity_values()` returns one value rather than a tuple. These methods also work with integer, string, UUID, and composite identities.

### Do not share one generated value as a class default

Use a factory:

```python
class Document(Model):
    _id: ID = Field(default_factory=ID, database=DatabaseField(primary_key=True))
```

Do not create one `ID` instance at class definition time if every document needs a distinct value:

```python
# Avoid this for generated identities.
class Document(Model):
    _id: ID = Field(default=ID(), database=DatabaseField(primary_key=True))
```

`default_factory=ID` is evaluated when each model instance is created.

## 6. Generated integer identities

Integer identities are different from generated string or UUID identities. `ID()` does not mint an integer; it returns an `ID` whose wrapped value is `None`, allowing the adapter to allocate the primary key.

For a conventional generated integer key, declare the field explicitly:

```python
from renus.db import DatabaseField, Field, Model


class Article(Model):
    id: int = Field(
        database=DatabaseField(
            primary_key=True,
            generated=True,
            auto_inc=True,
        ),
    )
    title: str
```

`auto_inc=True` must be used with `primary_key=True`. Database adapters may implement allocation differently, but the model metadata still describes the field as a generated primary key.

Use the `ID` field pattern instead when the same model should work with a configured identity such as a UUID, string, or document-database object ID.

## 7. String and UUID primary keys without `ID`

`ID` is not required for every non-integer primary key. Choose a concrete type when the model itself should control the identity format:

```python
from renus.db import DatabaseField, Field, Model


class Article(Model):
    slug: str = Field(
        database=DatabaseField(primary_key=True),
    )
    title: str
```

```python
from uuid import UUID, uuid4

from renus.db import DatabaseField, Field, Model


class ApiKey(Model):
    key: UUID = Field(
        default_factory=uuid4,
        database=DatabaseField(primary_key=True),
    )
    label: str
```

Use `ID` when the concrete identity should come from `config/database.py`; use `str` or `UUID` directly when the model requires that exact type.

## 8. Serialization

Renus converts an `ID` value to its string form in general model serialization:

```python
from renus.db import to_dict


payload = to_dict(document)
print(payload["_id"])
# a string representation of the identity
```

When data is loaded back into a model, Renus converts an identity field into an `ID` value using the configured identity type:

```python
from renus.db import from_dict


loaded = from_dict(
    Document,
    {
        "_id": "document-42",
        "title": "Loaded document",
    },
)

assert isinstance(loaded._id, ID)
```

The database adapter controls storage encoding. Document adapters can keep a native identity object in native form, while relational adapters store the identity in their supported representation. Application code should use `ID` and avoid depending on a backend-specific storage representation.

## 9. Identity configuration examples

### UUID identities

```python
# config/database.py
from uuid import UUID

ID = UUID
```

```python
from renus.datastructures import ID
from renus.db import DatabaseField, Field, Model


class Event(Model):
    id: ID = Field(
        default_factory=ID,
        database=DatabaseField(primary_key=True, generated=True),
    )
    name: str
```

### String identities

```python
# config/database.py
ID = str
```

```python
event = Event(name="release")
print(event.id.value)  # generated hexadecimal string
```

### Adapter-provided integer identities

```python
# config/database.py
ID = int
```

```python
class Event(Model):
    id: ID = Field(
        default_factory=ID,
        database=DatabaseField(
            primary_key=True,
            generated=True,
            auto_inc=True,
        ),
    )
    name: str
```

With integer configuration, the adapter supplies the value when the model is persisted.
