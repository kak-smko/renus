# Models and Fields

A Renus model is a Python class that describes application data. A model defines:

- the fields and their Python types;
- validation and default values;
- database columns and indexes;
- primary keys and generated identities;
- embedded data and relationships;
- timestamps, soft deletion, and lifecycle state.

Models are declared with `Model`, `Field`, and `DatabaseField` from `renus.db`.

## 1. Your first model

```python
from renus.db import DatabaseField, Field, Model


class User(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    username: str
    email: str
    active: bool = True
```

Create an instance with keyword arguments:

```python
user = User(
    username="alice",
    email="alice@example.com",
)

print(user.username)  # alice
print(user.active)    # True
print(user.to_dict())
```

A field without a default is required unless its annotation allows `None`. A field with a default is optional when the model is created.

```python
class Profile(Model):
    username: str                 # required
    bio: str | None = None        # optional and nullable
    login_count: int = 0          # optional with a default
```

A model can also be created from a dictionary:

```python
user = User({
    "username": "alice",
    "email": "alice@example.com",
})
```

## 2. Table names

The default table name is the lowercase plural of the class name:

```python
class User(Model):
    name: str


# User.metadata().table == "users"
```

Set an explicit table name with `Meta.table`:

```python
class AuditEntry(Model):
    message: str

    class Meta:
        table = "audit_log"
```

## 3. Python types and nullability

Renus reads the type annotation of each field. Common supported types include:

- `str`
- `int`
- `float`
- `bool`
- `bytes`
- `Decimal`
- `datetime`, `date`, and `time`
- `timedelta`
- `UUID`
- `dict` and `list`
- another `Model` type

Use a union with `None` to make a field nullable:

```python
from datetime import datetime
from uuid import UUID


class Event(Model):
    name: str
    occurred_at: datetime
    external_id: UUID | None = None
    notes: str | None = None
```

The annotation controls the expected Python value, nullability, and inferred database storage type. `str | None` means the field accepts `None`;

## 4. `Field` and `DatabaseField`

Use `Field` for application-level behavior:

- validation rules;
- defaults and default factories;
- custom validators;
- descriptions;
- sensitive-value masking.

Validation constraints are supplied as `Rule` instances, for example `Field(MinLen(3), MaxLen(30))`. Custom rules must inherit `Rule` and implement both `__call__()` and `json_schema()`.

Use `DatabaseField` for persistence behavior:

- column name and storage type;
- primary keys and generated values;
- nullability;
- indexes and uniqueness;
- database defaults;
- foreign keys and referential actions;
- immutable fields and comments.

They can be used together:

```python
from renus.db import DatabaseField, Field, Model
from renus.db.validation.rules import Email, MinLen


class Account(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    username: str = Field(
        MinLen(3),
        database=DatabaseField(unique=True, column_name="user_name"),
    )
    email: str = Field(
        Email(),
        database=DatabaseField(indexed=True),
    )
    status: str = Field(
        default="active",
        database=DatabaseField(indexed=True),
    )
```

Validation and persistence metadata remain separate. In this example, `MinLen(3)` validates the Python value, while `unique=True` and `column_name="user_name"` describe the database column.

### Database field options

```python
class Record(Model):
    id: int = Field(
        database=DatabaseField(
            primary_key=True,
            generated=True,
            auto_inc=True,
        )
    )
    public_name: str = Field(
        database=DatabaseField(
            column_name="display_name",
            indexed=True,
            index_name="idx_record_display_name",
        )
    )
    source: str = Field(
        default="imported",
        database=DatabaseField(
            immutable=True,
            comment="How this record entered the system",
        )
    )
```

`auto_inc=True` must be used with `primary_key=True`. A field marked `immutable=True` may be set while the model is new, but changing it after persistence raises `ValidationError`.

A database default and a Python default are different concerns:

```python
class Message(Model):
    # The Python value is used when Message is instantiated.
    state: str = Field(default="pending")

    # The factory creates a new value for each model instance.
    request_id: str = Field(
        default_factory=lambda: "request-generated-id",
        database=DatabaseField(indexed=True),
    )
```

Defaults belong to `Field`: use `default=...` for a fixed value and `default_factory=...` for a new value per instance. `DatabaseField` does not define Python defaults.

## 5. Validation

Validation happens when a model is instantiated and when a declared field is assigned after initialization. Invalid data raises `ValidationError`.

### Built-in `Field` checks

```python
from renus.db import Field, Model
from renus.db.validation.rules import In, Max, MaxLen, Min, MinLen, Regex


class Product(Model):
    name: str = Field(MinLen(2), MaxLen(100))
    price: float = Field(Min(0))
    status: str = Field(In("draft", "published"))
    code: str = Field(Regex(r"[A-Z]{3}-[0-9]{4}"))
```

Validation constraints are `Rule` instances. Use `Field(MinLen(2), MaxLen(100))`, `Field(In(...))`, or `Field(Regex(...))`. Custom rules must inherit `Rule` and implement `__call__()` and `json_schema()`. `default`, `default_factory`, `validator`, `validators`, `description`, and `sensitive` are `Field` options.

### Validation rules

Rules can be passed positionally. Renus includes rules such as `MinLen`, `MaxLen`, `Email`, `In`, `NotIn`, and `Regex` in `renus.db.validation.rules`:

```python
from renus.db import Field, Model
from renus.db.validation.rules import Email, In, MinLen


class User(Model):
    username: str = Field(MinLen(3))
    email: str = Field(Email())
    role: str = Field(In("admin", "member"))
```

A rule inherits `Rule`. Its `__call__()` method returns `True` for valid input or an error result for invalid input, and `json_schema()` returns the corresponding JSON Schema fragment:

```python
from typing import Any

from renus.db import Field, Model
from renus.db.validation import Rule


class PositiveNumber(Rule):
    def __call__(self, value: Any):
        if value is None or value > 0:
            return True
        return "must be positive"

    def json_schema(self):
        return {"exclusiveMinimum": 0}


class Invoice(Model):
    total: float = Field(PositiveNumber())
```

### Handling validation errors

`ValidationError.errors` contains field names mapped to lists of messages:

```python
from renus.db import ValidationError


try:
    User(username="ab", email="not-an-email", role="guest")
except ValidationError as error:
    print(error.errors)
    # {
    #     "username": ["'username' length must be at least 3"],
    #     "email": ["'email' is not a valid email address"],
    #     "role": ["'role' must be one of ['admin', 'member']"],
    # }
```

Pass dictionary input to the model constructor for validation:

```python
payload = {"username": "alice", "email": "alice@example.com", "role": "member"}
user = User(payload)
```

## 6. Nested models and embedded data

A model field annotated with another `Model` accepts either an instance of that model or a dictionary that Renus converts into an instance:

```python
from renus.db import Model


class Address(Model):
    street: str
    city: str


class Customer(Model):
    name: str
    address: Address


customer = Customer(
    name="Alice",
    address={
        "street": "123 Main St",
        "city": "Metropolis",
    },
)

assert isinstance(customer.address, Address)
```

A model annotation is an embedded relationship when declared explicitly with `Embedded` or `EmbeddedMany`:

```python
from renus.db import Embedded, EmbeddedMany, Model


class OrderItem(Model):
    product_name: str
    quantity: int


class Order(Model):
    number: str
    shipping_address: Address = Embedded(Address)
    items: list[OrderItem] = EmbeddedMany(OrderItem)
```

`Embedded` stores one related model inline. `EmbeddedMany` stores a collection inline. Both embedded relationship types cascade save, update, and delete behavior by default.

Plain `dict` and `list` annotations are also recognized as embedded data:

```python
class Document(Model):
    title: str
    metadata: dict
    tags: list
```

Use an explicit relationship when the target is another model and you need its relationship metadata. A raw `dict` or `list` annotation is treated as embedded data. Relationship targets must be model classes;

## 7. Relationships between models

Relationship declarations are descriptors. They also become query paths when accessed on the model class, for example `Customer.name` or `Customer.address.city`.

### Relationship types

| Declaration | Value on the owner | Use it for |
| --- | --- | --- |
| `Embedded(Target)` | One target | Inline one nested model |
| `EmbeddedMany(Target)` | List of targets | Inline nested models |
| `OneToOne(Target)` | One target | One related record |
| `OneToMany(Target)` | List of targets | Parent-to-children collection |
| `ManyToOne(Target)` | One target | Child-to-parent reference |
| `ManyToMany(Target)` | List of targets | Collection connected through an intermediate model or table |
| `Reference(Target)` | One target by default | A general non-embedded reference |

### One-to-one and one-to-many

The `foreign_key` is the field on the target model used for the join:

```python
from renus.db import DatabaseField, Field, Model, OneToMany, OneToOne


class Profile(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    bio: str
    user_id: int


class Post(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    title: str
    user_id: int


class User(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str
    profile: Profile = OneToOne(Profile, foreign_key="user_id")
    posts: list[Post] = OneToMany(Post, foreign_key="user_id")
```

### Many-to-one

Use `ManyToOne` from the model that stores the foreign key:

```python
from renus.db import ManyToOne


class Department(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    name: str


class Employee(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    department_id: int
    department: Department = ManyToOne(
        Department,
        foreign_key="department_id",
    )
```

`local_key` changes the field on the owner used for the join. If omitted, the owner's primary key is used. If `foreign_key` is omitted, the target primary key is used.

### Many-to-many

Specify the intermediate model or table with `through`:

```python
from renus.db import ManyToMany


class Role(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    name: str


class User(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str
    roles: list[Role] = ManyToMany(Role, through="user_roles")
```

### Relationship options

Declare the target with its model class.

```python
class Child(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    parent_id: int


class Parent(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    children: list[Child] = OneToMany(Child, foreign_key="parent_id")
```

Reference relationships support:

- `on_save`: `"cascade"` or `"no action"`;
- `on_delete`: `"cascade"`, `"restrict"`, `"set null"`, `"set default"`, or `"no action"`;
- `on_update`: the same referential actions;
- `loading`: `"lazy"` or `"joined"`;
- `local_key` and `foreign_key`;
- `through` for `ManyToMany`.

For example:

```python
posts: list[Post] = OneToMany(
    Post,
    foreign_key="user_id",
    on_save="cascade",
    on_delete="cascade",
    loading="joined",
)
```

The default loading strategy is `"lazy"`. The default save action is `"no action"` for reference relationships. Embedded relationships use cascading behavior by default.

## 8. Primary keys and identities

Renus determines a model identity from its primary-key fields.

### Generated integer identity

Declare an integer primary key when the backend should generate it:

```python
class Article(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    title: str
```

If no identity field is declared, Renus synthesizes a generated integer `id` field. Declaring it explicitly is clearer when configuring database behavior such as `auto_inc=True`.

### String identity

```python
class Slug(Model):
    slug: str = Field(
        database=DatabaseField(primary_key=True)
    )
    title: str
```

```python
article = Slug(slug="portable-orm", title="Portable ORM")
print(article.identity_values())  # portable-orm
```

### UUID identity

```python
from uuid import UUID, uuid4


class ApiKey(Model):
    id: UUID = Field(
        default_factory=uuid4,
        database=DatabaseField(primary_key=True),
    )
    label: str
```

### Configured `ID` identity

`ID` is a value object for a configured identity type:

```python
from renus.db import DatabaseField, Field, ID, Model


class Document(Model):
    _id: ID = Field(
        default_factory=ID,
        database=DatabaseField(primary_key=True),
    )
    title: str
```

The configured identity object is read from `Config("database")` under `ID`. `ID` can wrap an existing value or create one using the configured identity factory. An integer identity is left for the database adapter to allocate.

### Composite identity

Mark more than one field as `primary_key`:

```python
class Membership(Model):
    organization_id: int = Field(
        database=DatabaseField(primary_key=True)
    )
    user_id: int = Field(
        database=DatabaseField(primary_key=True)
    )
    role: str
```

```python
membership = Membership(
    organization_id=10,
    user_id=42,
    role="admin",
)

print(membership.identity_values())  # (10, 42)
print(membership.identity_dict())    # {"organization_id": 10, "user_id": 42}
```

For a single-key model, `identity_values()` returns the value itself. For a composite-key model, it returns a tuple.

## 9. Timestamps and soft deletion

Enable timestamp fields with `Meta.timestamps`:

```python
class Article(Model):
    title: str

    class Meta:
        timestamps = True
```

Renus adds `created_at` and `updated_at`. New instances receive UTC timestamps.

Enable soft deletion with `Meta.soft_delete`:

```python
class Product(Model):
    sku: str
    price: float

    class Meta:
        timestamps = True
        soft_delete = True
```

Soft-deletable models receive:

- `deleted_at`, initially `None`;
- `is_deleted()`, initially `False`.

Call `soft_delete()` and `restore()` on the model:

```python
product = Product(sku="ITEM-1", price=19.99)

product.soft_delete()
assert product.is_deleted() is True
assert product.deleted_at is not None

product.restore()
assert product.is_deleted() is False
assert product.deleted_at is None
```

Calling either method on a model without `soft_delete = True` raises `ValueError`. When a repository deletes a soft-deletable model, it updates the soft-delete fields instead of physically removing the record.

## 10. Model lifecycle and dirty fields

A new model starts in the `NEW` state. A repository marks it `PERSISTED` after a successful insert. Changing a persisted field changes the state to `DIRTY`.

```python
from renus.db import Lifecycle


article = Article(title="Draft")
assert article.state() == Lifecycle.NEW
assert article.is_new() is True
assert article.is_dirty() is False

# After: await repository.create(article)
assert article.is_persisted() is True

article.title = "Published"
assert article.is_dirty() is True
assert article.dirty_fields() == {"title"}
assert article.get_dirty_changes() == {
    "title": ("Draft", "Published"),
}
```

Useful lifecycle properties and methods are:

| API | Purpose |
| --- | --- |
| `state()` | Current `Lifecycle` value |
| `is_new()` | Whether the model has not been persisted |
| `is_persisted()` | Whether it is persisted and clean |
| `is_dirty()` | Whether a persisted value changed |
| `is_deleted()` | Whether the model has been deleted |
| `dirty_fields()` | Names of changed fields |
| `get_dirty_changes()` | Original and current values for changed fields |
| `identity_values()` | Primary-key value or tuple |
| `identity_dict()` | Primary-key fields as a dictionary |

Use a repository to persist state changes:

```python
article = Article(title="Draft")
await articles.create(article)

article.title = "Published"
await articles.save(article)
```

`save()` inserts a new model and updates an existing dirty model. See [Database Overview](overview.md) and [Queries](queries.md) for repository and query setup.

## 11. Sensitive fields

Mark secrets with `sensitive=True`:

```python
class Credential(Model):
    username: str
    password_hash: str = Field(sensitive=True)
    access_token: str | None = Field(default=None, sensitive=True)
```

Sensitive fields are masked when read normally:

```python
credential = Credential(
    username="alice",
    password_hash="hashed-value",
)

print(credential.password_hash)  # ***
print(credential.get_sensitive("password_hash"))  # hashed-value
```

The model's `to_dict()` and `dict()` output does not expose sensitive fields. The database serialization helper is also safe by default:

```python
from renus.db import to_dict

safe = to_dict(credential)
with_secrets = to_dict(credential, include_sensitive=True)
```

Only use `include_sensitive=True` when the destination is trusted.

## 12. Serialization

### Model methods

`to_dict()` and `dict()` return the model as a plain Python dictionary. Nested models, lists, tuples, and dictionaries are converted recursively:

```python
payload = customer.to_dict()
print(payload["address"]["city"])
```

### JSON-compatible serialization

The helpers exported from `renus.db` convert values such as `UUID`, `ID`, `datetime`, `date`, `Decimal`, enums, and bytes into JSON-compatible values:

```python
from renus.db import from_dict, from_json, to_dict, to_json


payload = to_dict(customer, exclude_none=True)
json_payload = to_json(customer, indent=2)

same_customer = from_dict(Customer, payload)
restored_customer = from_json(Customer, json_payload)
```

Serialization filters:

```python
payload = to_dict(
    customer,
    exclude_none=True,
    include=["name", "address"],
    exclude=["internal_notes"],
)
```

`from_dict` and `from_json` validate by default. Pass `validate=False` only when the input has already been validated:

```python
customer = from_dict(Customer, payload, validate=False)
```

## 13. JSON Schema

`Model.schema()` returns a JSON-serializable JSON Schema document for a model. The schema uses the JSON Schema draft 2020-12 vocabulary and is built from the model's annotations, field defaults and descriptions, validation rules, and relationship metadata. It describes data shape; it does not create database tables or replace runtime validation.

```python
from renus.db import Field, Model
from renus.db.validation.rules import MaxLen, MinLen


class Profile(Model):
    display_name: str = Field(MinLen(1), MaxLen(80))
    bio: str | None = None


schema = Profile.schema()
assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
assert schema["properties"]["display_name"]["minLength"] == 1
```

The root schema is an object with `title`, `properties`, and `additionalProperties: true`. Non-nullable fields without defaults are listed in `required`. Nullable annotations allow `null`. Non-nullable fields without defaults are listed in `required`; a validation rule marked as required can also add a property to that list. Declared defaults are included after conversion to JSON-compatible values. Built-in Python types map to JSON Schema types (for example, `int` to `integer` and `datetime` to a `string` with `date-time` format). A field's `Field` description and validation-rule schema fragments are included when present. Custom validation rules contribute only the fragment returned by their `json_schema()` method; rules that return `{}` add no schema constraints.

Nested model fields and model collections are represented recursively. Relationships are included as properties, including relationships declared without a Python annotation such as `items = EmbeddedMany(Item)`. Recursive model references use `$defs` and `$ref` to avoid infinitely nested schemas. Non-collection relationship properties allow `null`; collection relationships are represented as arrays.

The schema documents validation shape, but it cannot capture arbitrary Python validation logic or custom runtime types unless a rule provides a JSON Schema fragment. Inspect or extend the rule's `json_schema()` implementation when the generated schema needs additional constraints.

## 14. Indexes and field-level database rules

Field-level `unique=True` and `indexed=True` create indexes from the field declaration. Use `Meta.indexes` for a multi-column index:

```python
from renus.db import DatabaseField, Field, Index, Model


class Employee(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    department: str
    employee_code: str

    class Meta:
        indexes = (
            Index(
                "department",
                "employee_code",
                unique=True,
                name="idx_employee_department_code",
            ),
        )
```

Use `Field` validation options and `Rule` instances for application-level data rules.

```python
class Assignment(Model):
    organization_id: int = Field(database=DatabaseField(primary_key=True))
    employee_id: int = Field(database=DatabaseField(primary_key=True))
    hours: int = Field(Min(1))

    class Meta:
        indexes = (
            Index("organization_id", "employee_id", unique=True),
        )
```

The multi-column `Index(..., unique=True)` enforces uniqueness through the backend index.

A single field can also declare a foreign-key target:

```python
class Post(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    user_id: int = Field(
        database=DatabaseField(
            foreign_key="users.id",
            on_delete="cascade",
            on_update="cascade",
        )
    )
```

## 15. Inspecting model metadata

Use `Model.metadata()` to inspect the resolved schema description:

```python
meta = User.metadata()

print(meta.table)
print(meta.primary_key_fields)
print(meta.identity.kind)
print(meta.fields["username"].column_name)
print(meta.fields["username"].required)
print(meta.relationships)
print(meta.indexes)
```

`ModelMetadata` provides:

- `table`: resolved table or collection name;
- `fields`: field names mapped to `FieldMetadata`;
- `column_to_field`: reverse column-name lookup;
- `identity`: `IdentityMetadata` for the primary key;
- `relationships`: resolved relationship metadata;
- `indexes`: field and `Meta` indexes;
- timestamp and soft-delete flags.

Useful lookup methods and properties:

```python
field = meta.get_field("username")
assert field is meta.get_field(field.column_name)

assert meta.is_primary_key("id")
assert meta.primary_key_fields == ("id",)
assert meta.primary_key_field == "id"
```

`primary_key_field` is for single-column identities. It raises `ValueError` for composite identities; use `primary_key_fields` instead.

## 16. A complete model example

This example combines the main model features:

```python
from renus.db import (
    DatabaseField,
    Embedded,
    Field,
    Model,
    OneToMany,
)
from renus.db.validation.rules import Email, MinLen


class Address(Model):
    street: str
    city: str
    country: str = "US"


class Post(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    title: str = Field(MinLen(3))
    user_id: int


class User(Model):
    id: int = Field(
        database=DatabaseField(primary_key=True, generated=True)
    )
    username: str = Field(
        MinLen(3),
        database=DatabaseField(unique=True),
    )
    email: str = Field(Email())
    address: Address = Embedded(Address)
    posts: list[Post] = OneToMany(
        Post,
        foreign_key="user_id",
        on_save="cascade",
    )

    class Meta:
        table = "users"
        timestamps = True
        soft_delete = True
```

```python
user = User(
    username="alice",
    email="alice@example.com",
    address={
        "street": "123 Main St",
        "city": "Metropolis",
    },
    posts=[
        {"title": "First post", "user_id": 1},
    ],
)

print(user.address.city)
print(user.posts[0].title)
print(user.metadata().table)  # users
```

From here:

- persist instances through a model repository;
- use model class paths such as `User.username` in [Queries](queries.md);
- use [Adapters](adapters.md) for backend-specific storage behavior.
