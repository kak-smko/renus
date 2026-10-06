# Fields

A field is a model attribute that describes one value in your application data. In Renus, a field can define:

- the Python type of the value;
- whether the value is required or nullable;
- a default value or a default factory;
- validation and conversion rules;
- the database column and persistence behavior;
- whether the value is sensitive or immutable.

The two main field declarations are:

- `Field` — application-level behavior such as defaults, validation, conversion, descriptions, and masking.
- `DatabaseField` — database-level behavior such as column names, primary keys, indexes, and foreign keys.

They are usually combined:

```python
from renus.db import DatabaseField, Field, Model


class User(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    username: str
```

## 1. The smallest useful field

Declare a model by adding type annotations to a `Model` subclass:

```python
from renus.db import Model


class User(Model):
    name: str
    age: int
    active: bool
```

Renus reads the annotations when the model class is created. The annotations are used for validation and for inferring database storage types.

Create an instance with keyword arguments:

```python
user = User(name="Ada", age=36, active=True)

print(user.name)  # Ada
```

A field without a default is required unless its annotation allows `None`:

```python
User(name="Ada", age=36)  # ValidationError: active is required
```

A model that does not declare an identity field receives a generated integer `id` field. You can declare the identity explicitly when you need to control its type or database behavior; see [Primary keys](#primary-keys-and-generated-values).

## 2. Python types

Renus checks assigned values against the annotation. Common supported annotations include:

| Annotation | Accepted value | Inferred storage type |
| --- | --- | --- |
| `str` | `str` | `str` |
| `int` | `int` (but not `bool`) | `int` |
| `float` | `float` or `int` (but not `bool`) | `float` |
| `bool` | `bool` | `bool` |
| `bytes` | `bytes` | `bytes` |
| `date` | `date` or `datetime` | `date` |
| `datetime` | `datetime` | `datetime` |
| `time` | `time` | `time` |
| `timedelta` | `timedelta` | `timedelta` |
| `Decimal` | `Decimal` | `Decimal` |
| `UUID` | `UUID` | `UUID` |
| `ID` | `ID` | `ID` |
| `list` | `list` | `list` |
| `dict` | `dict` | `dict` |
| another `Model` | that model or a dictionary for it | inferred from the model field |

For example:

```python
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from renus.db import Model


class Event(Model):
    title: str
    starts_at: datetime
    event_date: date
    starts_time: time
    price: Decimal
    external_id: UUID
    metadata: dict
```

A `float` field accepts integers as well as floats. An `int` field does not accept booleans, even though `bool` is a subclass of `int` in Python. Database adapters encode `datetime`, `date`, and `time` values to ISO strings when needed and decode them back according to the declared field type. A `time` field therefore round-trips values such as `time(8, 15, 30)` without requiring application-level serialization.

## 3. Nullable fields

Add `None` to the annotation to make a field nullable:

```python
from renus.db import Model


class Profile(Model):
    display_name: str
    bio: str | None
    website: str | None = None
```

These declarations have different meanings:

- `bio: str | None` is nullable, so it can be omitted and becomes `None`.
- `website: str | None = None` is also nullable and explicitly declares a Python default.
- `display_name: str` is required and cannot be `None`.

Nullability comes from the type annotation. A validation rule such as `Required()` can reject `None` when the field is otherwise nullable, but it does not change the database metadata's inferred nullability.

## 4. Defaults

Use `Field(default=...)` for a fixed Python default:

```python
from renus.db import Field, Model


class Task(Model):
    title: str
    status: str = Field(default="pending")
    attempts: int = Field(default=0)
```

The default is applied when the value is omitted. It is also considered when a value of `None` is cleaned by the field.

Use `default_factory` when each instance needs a newly created value:

```python
from datetime import datetime, timezone
from uuid import uuid4

from renus.db import Field, Model


class Request(Model):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
```

Do not use a mutable object as a shared static default:

```python
# Prefer this: a new list is created for every instance.
labels: list[str] = Field(default_factory=list)

# Avoid using one shared mutable list as a class-level default.
```

A callable supplied as `default` is also called when the default is resolved, but `default_factory` is the clearer choice for generated values.


## 5. `Field` validation

Pass validation rules positionally to `Field`:

```python
from renus.db import Field, Model
from renus.db.validation.rules import In, MaxLen, Min, MinLen, Regex


class Product(Model):
    name: str = Field(MinLen(2), MaxLen(100))
    price: float = Field(Min(0))
    status: str = Field(In("draft", "published"))
    code: str = Field(Regex(r"[A-Z]{3}-[0-9]{4}"))
```

Built-in rules are callable `Rule` objects. Every rule implements `json_schema()` so it can describe its JSON Schema fragment. Common rules include:

| Rule | Purpose | Example |
| --- | --- | --- |
| `Len(n)` | exact length | `Len(8)` |
| `MinLen(n)` | minimum length | `MinLen(3)` |
| `MaxLen(n)` | maximum length | `MaxLen(120)` |
| `Eq(value)` | exact value | `Eq("active")` |
| `Min(value)` | minimum numeric value | `Min(0)` |
| `Max(value)` | maximum numeric value | `Max(100)` |
| `In(*values)` | allow only listed values | `In("draft", "live")` |
| `NotIn(*values)` | reject listed values | `NotIn("banned")` |
| `Email()` | validate an email address | `Email()` |
| `Regex(pattern)` | require a full regular-expression match | `Regex(r"[A-Z]+")` |
| `Url` | validate a URL | `Field(Url)` |
| `Ip` | validate an IPv4 address | `Field(Ip)` |
| `Numeric` | require digits | `Field(Numeric)` |
| `Accepted` | accept common affirmative values | `Field(Accepted)` |

Import rules from `renus.db.validation.rules`:

```python
from renus.db.validation.rules import Email, In, MaxLen, MinLen
```

A rule can return:

- `True` when the value is valid;
- `False` for a generic validation error;
- an error-compatible result returned by the built-in rules;
- a transformed value, when the rule is intended to normalize input.

Rules run before Renus performs the field's type check.

### Custom validation rules

Custom rules must inherit `Rule` and implement both `__call__()` and `json_schema()`. Return `True` for a valid value or return an error-compatible result for invalid input:

```python
from typing import Any

from renus.db import Field, Model
from renus.db.validation import Rule


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

`Field` rejects plain functions, lambdas, and other opaque callables. If a rule cannot be expressed in JSON Schema, return `{}` from `json_schema()`. The runtime callable may still normalize values by returning the transformed value, but the rule remains an explicit `Rule` class.


## 6. When validation runs

Renus validates declared fields in two places:

1. when a model instance is created;
2. when a declared field is assigned after initialization.

```python
from renus.db import Field, Model, ValidationError
from renus.db.validation.rules import MinLen


class User(Model):
    username: str = Field(MinLen(3))


try:
    user = User(username="ab")
except ValidationError as error:
    print(error.errors)
    # {"username": ["'username' length must be at least 3"]}


user = User(username="ada")
try:
    user.username = "a"
except ValidationError as error:
    print(error.errors)
```

`ValidationError.errors` maps each field name to a list of messages. This makes it suitable for returning field-specific errors from an application boundary.

For dictionaries or JSON objects, pass the dictionary to the model constructor:

```python
payload = {"username": "ada"}
user = User(payload)
```

The model constructor validates the dictionary and constructs a validated model.

## 7. Nested model fields

A field can contain another `Model`. A dictionary assigned to that field is converted into the nested model and validated:

```python
from renus.db import Model


class Address(Model):
    city: str
    country: str


class Customer(Model):
    name: str
    address: Address


customer = Customer(
    name="Ada",
    address={"city": "London", "country": "UK"},
)

assert isinstance(customer.address, Address)
```

A nested field also accepts an instance of the nested model:

```python
address = Address(city="London", country="UK")
customer = Customer(name="Ada", address=address)
```

A list annotated with a model type converts each dictionary item:

```python
class OrderItem(Model):
    sku: str
    quantity: int


class Order(Model):
    items: list[OrderItem]


order = Order(
    items=[
        {"sku": "BOOK-1", "quantity": 2},
        {"sku": "PEN-1", "quantity": 5},
    ]
)

assert all(isinstance(item, OrderItem) for item in order.items)
```

Nested validation errors include the path to the invalid value, such as `address.city` or `items[0].quantity`.

## 8. Database column metadata

Use `DatabaseField` inside `Field(database=...)` to describe persistence behavior:

```python
from renus.db import DatabaseField, Field, Model


class Record(Model):
    id: int = Field(
        database=DatabaseField(
            primary_key=True,
            generated=True,
            auto_inc=True,
        )
    )
    display_name: str = Field(
        database=DatabaseField(
            column_name="display_name",
            indexed=True,
            index_name="idx_record_display_name",
        )
    )
```

The Python attribute remains `display_name`, while the database column is `display_name`. If `column_name` is omitted, the field name is used as the column name.

A `DatabaseField` can also be assigned directly. Renus turns it into a `Field` declaration when the model class is created:

```python
from renus.db import DatabaseField, Model


class User(Model):
    id: int = DatabaseField(primary_key=True, generated=True)
```

The explicit `Field(database=...)` form is useful when the same field also needs validation, a default, or masking.

### `DatabaseField` options

`DatabaseField` is immutable and supports these options:

| Option | Meaning |
| --- | --- |
| `column_name` | Physical column name. Defaults to the Python field name. |
| `primary_key` | Makes the field part of the model identity. |
| `auto_inc` | Requests auto-increment behavior from the adapter. Must be used with `primary_key=True`. |
| `identity_kind` | Explicit identity kind; it can be an `IdentityKind` value or its string value. |
| `generated` | Marks the value as generated by the database or persistence layer. |
| `unique` | Creates a unique field index. |
| `indexed` | Creates a non-unique field index. |
| `index_name` | Optional name for the generated field index. |
| `foreign_key` | Foreign-key target, such as `"users.id"`. |
| `on_delete` | Referential action for deletion. |
| `on_update` | Referential action for updates. |
| `immutable` | Prevents changing the value after the model is persisted. |
| `comment` | Comment associated with the database field metadata. |


## 9. Primary keys and generated values

A primary key is declared with `primary_key=True`:

```python
class Article(Model):
    id: int = Field(
        database=DatabaseField(
            primary_key=True,
            generated=True,
            auto_inc=True,
        )
    )
    title: str
```

If the type and database metadata do not specify an identity kind, Renus infers it from the field type. The supported identity kinds include integer, string, UUID, `ID`, generated, and composite identities.

### String and UUID identities

```python
from uuid import UUID, uuid4


class Slug(Model):
    slug: str = Field(
        database=DatabaseField(primary_key=True)
    )
    title: str


class ApiKey(Model):
    key: UUID = Field(
        default_factory=uuid4,
        database=DatabaseField(primary_key=True),
    )
    label: str
```

For an `ID` identity, use the `ID` type and its factory:

```python
from renus.db import DatabaseField, Field, ID, Model


class Document(Model):
    _id: ID = Field(
        default_factory=ID,
        database=DatabaseField(primary_key=True),
    )
    title: str
```

### Composite identities

Multiple fields can be primary-key fields:

```python
class Membership(Model):
    user_id: int = Field(
        database=DatabaseField(primary_key=True)
    )
    group_id: int = Field(
        database=DatabaseField(primary_key=True)
    )
    role: str
```

A composite identity has more than one field. Code that requires one primary-key field must handle this case explicitly.

## 10. Indexes and uniqueness

Mark a field as indexed or unique with `DatabaseField`:

```python
class Employee(Model):
    email: str = Field(
        database=DatabaseField(
            unique=True,
            index_name="idx_employee_email",
        )
    )
    department_id: int = Field(
        database=DatabaseField(indexed=True)
    )
```

`unique=True` also makes the field indexed in the resolved model metadata. A unique index is a database constraint; it is not a replacement for application-level validation because the final constraint is enforced when persistence occurs.

For a multi-field index, declare an `Index` in the model's `Meta` class:

```python
from renus.db import Index, Model


class Assignment(Model):
    employee_id: int
    project_id: int

    class Meta:
        indexes = (
            Index("employee_id", "project_id", unique=True),
        )
```

Field-level `indexed` and `unique` options create single-field indexes. `Meta.indexes` supports indexes containing multiple fields.

## 11. Foreign keys

Store a foreign-key target in `DatabaseField`:

```python
class Post(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    user_id: int = Field(
        database=DatabaseField(
            foreign_key="users.id",
            on_delete="cascade",
            on_update="cascade",
        )
    )
    title: str
```

`foreign_key`, `on_delete`, and `on_update` are database metadata. They do not create a Python relationship attribute by themselves. Use Renus relationship declarations when you need model-to-model loading or navigation.

## 12. Immutable fields

An immutable field can be set while a model is new, but cannot be changed after persistence:

```python
class Account(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    account_number: str = Field(
        database=DatabaseField(immutable=True)
    )
    balance: int = 0
```

After the repository marks the model as persisted, assigning a different `account_number` raises `ValidationError`. This protects values that must remain stable while allowing normal updates to other fields.

## 13. Sensitive fields

Set `sensitive=True` to mask a field when it is read as a model attribute:

```python
class Credential(Model):
    username: str
    password: str = Field(sensitive=True)
    token: str | None = Field(default=None, sensitive=True)
```

For a non-`None` sensitive value:

```python
credential = Credential(username="ada", password="secret")

print(credential.password)                  # ***
print(credential.get_sensitive("password"))  # secret
```

`get_sensitive(name)` returns the raw value for code that is explicitly authorized to access it. Treat that method as a deliberate boundary around secret data.

## 14. Field descriptions and custom errors

Use `description` to attach human-readable field metadata:

```python
class Profile(Model):
    biography: str | None = Field(
        default=None,
        description="A short public biography.",
    )
```

Use `error` to provide a format string for compatible rule errors:

```python
from renus.db import Field, Model
from renus.db.validation.rules import Min


class Score(Model):
    value: int = Field(
        Min(10),
        error="{0} must be at least {1}; received {2}.",
    )
```

The format fields are the field name followed by the context supplied by the validation rule. If a custom format cannot be applied, Renus uses the normal rule error instead.

## 15. Fields and model state

Renus validates field assignment and tracks changes after a model is persisted:

```python
user = User(name="Ada", age=36, active=True)

print(user.is_new())       # True
print(user.is_dirty())     # False

# After repository persistence, changing a declared field marks the model dirty.
user.name = "Ada Lovelace"
print(user.dirty_fields())
print(user.get_dirty_changes())
```

The model exposes:

- `is_new()` — the model has not been persisted;
- `is_persisted()` — the model is persisted and unchanged;
- `is_dirty()` — a persisted model has changed;
- `is_deleted()` — the model is marked deleted;
- `dirty_fields()` — names of changed fields;
- `get_dirty_changes()` — changed field names and values;
- `identity_values()` — primary-key values;
- `identity_dict()` — primary-key names and values.

Assignment validation happens before a value is stored. If assignment raises `ValidationError`, the invalid value is not accepted.

## 16. Inspecting resolved field metadata

Every model has resolved metadata at `metadata()`. Use it when building tooling, migrations, serializers, or diagnostics:

```python
metadata = User.__db_metadata__

print(metadata.table)
print(metadata.primary_key_fields)

username = metadata.get_field("username")
print(username.column_name)
print(username.python_type)
print(username.required)
print(username.unique)
```

`ModelMetadata.fields` maps Python field names to immutable `FieldMetadata` objects. A `FieldMetadata` object contains the resolved values for:

- `name` and `column_name`;
- `python_type`, `inferred_type`, and `storage_type`;
- `nullable` and `required`;
- `primary_key`, `identity_kind`, and `generated`;
- `unique`, `indexed`, and `index_name`;
- `default` and `default_factory`;
- `foreign_key`, `on_delete`, and `on_update`;
- `immutable`, `comment`, and `sensitive`.

Look up a field by either its Python attribute name or its database column name:

```python
metadata.get_field("username")
metadata.get_field("user_name")  # works if column_name="user_name"
```

Field metadata is resolved when the model class is created, so it reflects the complete declaration rather than only the `Field` object written in the class body.

## 17. Complete example

The following model combines typing, defaults, validation, database mapping, indexes, and a nested field:

```python
from datetime import datetime, timezone
from uuid import uuid4

from renus.db import DatabaseField, Field, Index, Model
from renus.db.validation.rules import Email, In, MaxLen, MinLen


class Address(Model):
    city: str = Field(MinLen(2), MaxLen(80))
    country: str = Field(MinLen(2), MaxLen(80))


class User(Model):
    id: int = Field(
        database=DatabaseField(
            primary_key=True,
            generated=True,
            auto_inc=True,
        )
    )
    public_id: str = Field(
        default_factory=lambda: str(uuid4()),
        database=DatabaseField(unique=True),
    )
    username: str = Field(
        MinLen(3),
        MaxLen(40),
        database=DatabaseField(
            column_name="user_name",
            indexed=True,
        ),
    )
    email: str = Field(
        Email(),
        database=DatabaseField(unique=True),
    )
    role: str = Field(
        default="member",
        validator=In("admin", "member"),
    )
    address: Address | None = None
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    password: str = Field(sensitive=True)

    class Meta:
        indexes = (
            Index("role", "joined_at"),
        )


user = User(
    username="ada",
    email="ada@example.com",
    address={"city": "London", "country": "UK"},
    password="not-for-display",
)

print(user.username)                 # ada
print(user.password)                 # ***
print(user.get_sensitive("password"))  # not-for-display
print(user.address.city)             # London
```

## Field checklist

When adding a field, decide in this order:

1. **What Python value should it accept?** Add the correct annotation.
2. **Can it be absent or `None`?** Use a nullable annotation such as `str | None`.
3. **Does it need a default?** Use `default` for a fixed value or `default_factory` for a new value per instance.
4. **What application rules apply?** Add built-in rules or custom validators.
5. **How should it be stored?** Add `DatabaseField` for column and persistence metadata.
6. **Does it identify the row?** Set `primary_key=True` and configure generation if required.
7. **Should it be searchable or unique?** Set `indexed=True` or `unique=True`.
8. **Should it remain unchanged?** Set `immutable=True`.
9. **Is it secret?** Set `sensitive=True`.
10. **Do nested values need their own validation?** Annotate the field with another `Model` or `list[Model]`.

For model-level behavior such as relationships, timestamps, soft deletion, serialization, and lifecycle operations, continue to [Models](models.md). For creating and querying stored records, see [Database Overview](overview.md).
