from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from renus.db import (
    CheckConstraint,
    DatabaseField,
    Embedded,
    EmbeddedMany,
    EmbeddedOne,
    Field,
    FieldMetadata,
    ForeignKeyConstraint,
    IdentityKind,
    IdentityMetadata,
    Index,
    Lifecycle,
    ManyToMany,
    ManyToOne,
    ModelMetadata,
    ID,
    OneToMany,
    OneToOne,
    Path,
    Model,
    Reference,
    RelationshipKind,
    RelationshipMetadata,
    UniqueConstraint,
    ValidationError,
)
from renus.db.query.ast import Operator
from renus.db.validation.rules import Email, MinLen


class ComprehensiveTypesModel(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str
    age: int
    score: float
    is_active: bool
    data: bytes
    price: Decimal
    created: datetime
    birthday: date
    start_time: time
    duration: timedelta
    token: UUID
    metadata_doc: dict
    tags: list
    bio: str | None = None
    optional_int: int | None = None

def test_type_annotation_schema_inference():
    meta = ComprehensiveTypesModel.metadata()
    assert isinstance(meta, ModelMetadata)
    assert meta.table == "comprehensivetypesmodels"

    assert not meta.fields["name"].nullable
    assert not meta.fields["age"].nullable
    assert meta.fields["bio"].nullable
    assert meta.fields["optional_int"].nullable

    assert meta.fields["name"].storage_type is str
    assert meta.fields["age"].storage_type is int
    assert meta.fields["score"].storage_type is float
    assert meta.fields["is_active"].storage_type is bool
    assert meta.fields["data"].storage_type is bytes
    assert meta.fields["price"].storage_type is Decimal
    assert meta.fields["created"].storage_type is datetime
    assert meta.fields["birthday"].storage_type is date
    assert meta.fields["start_time"].storage_type is time
    assert meta.fields["duration"].storage_type is timedelta
    assert meta.fields["token"].storage_type is UUID

    assert "metadata_doc" not in meta.fields
    assert "tags" not in meta.fields
    assert meta.relationships["metadata_doc"].kind == RelationshipKind.EMBEDDED_ONE
    assert meta.relationships["metadata_doc"].is_embedded
    assert meta.relationships["tags"].kind == RelationshipKind.EMBEDDED_MANY
    assert meta.relationships["tags"].is_embedded
    assert meta.relationships["tags"].is_collection

def test_custom_storage_type_override():
    class CustomTypeModel(Model):
        id: int = Field(database=DatabaseField(primary_key=True))
        code: str = Field(database=DatabaseField(storage_type="VARCHAR(64)"))

    meta = CustomTypeModel.metadata()
    assert meta.fields["code"].storage_type == "VARCHAR(64)"

class UserSeparatedModel(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(MinLen(3), database=DatabaseField(unique=True, column_name="u_name"))
    email: str = Field(Email(), db=DatabaseField(indexed=True))
    status: str = Field(database=DatabaseField(default="active", indexed=True))

def test_separation_of_validation_and_persistence():
    meta = UserSeparatedModel.metadata()
    f_username = meta.fields["username"]

    assert f_username.column_name == "u_name"
    assert f_username.unique is True
    assert f_username.database.unique is True

    assert f_username.validation is not None
    assert any(isinstance(r, MinLen) for r in f_username.validation.rules)

    assert meta.column_to_field["u_name"] == "username"
    assert meta.get_field("u_name") == f_username
    assert meta.get_field("username") == f_username

def test_validation_enforcement():

    with pytest.raises(ValidationError):
        UserSeparatedModel(username="ab", email="user@example.com")

    with pytest.raises(ValidationError):
        UserSeparatedModel(username="valid_user", email="not-an-email")

    user = UserSeparatedModel(username="valid_user", email="user@example.com")
    assert user.username == "valid_user"
    assert user.status == "active"

def test_integer_auto_increment_identity():
    class IntModel(Model):
        id: int = Field(database=DatabaseField(primary_key=True, generated=True))
        title: str

    meta = IntModel.metadata()
    assert meta.identity.kind == IdentityKind.INTEGER
    assert meta.identity.generated is True
    assert meta.primary_key_field == "id"
    assert not meta.identity.is_composite

def test_uuid_identity():
    uid = uuid4()

    class UuidModel(Model):
        id: UUID = Field(database=DatabaseField(primary_key=True, default_factory=uuid4))
        title: str

    meta = UuidModel.metadata()
    assert meta.identity.kind == IdentityKind.UUID
    assert meta.primary_key_field == "id"

    instance = UuidModel(id=uid, title="Test UUID")
    assert instance.identity_values == uid
    assert instance.identity_dict == {"id": uid}

def test_string_identity():
    class SlugModel(Model):
        slug: str = Field(database=DatabaseField(primary_key=True))
        name: str

    meta = SlugModel.metadata()
    assert meta.identity.kind == IdentityKind.STRING
    assert meta.primary_key_field == "slug"

    item = SlugModel(slug="portable-orm", name="Portable ORM")
    assert item.identity_values == "portable-orm"

def test_composite_identity():
    class CompositeModel(Model):
        org_id: int = Field(database=DatabaseField(primary_key=True))
        user_id: int = Field(database=DatabaseField(primary_key=True))
        role: str

    meta = CompositeModel.metadata()
    assert meta.identity.kind == IdentityKind.COMPOSITE
    assert meta.identity.is_composite is True
    assert meta.identity.fields == ("org_id", "user_id")

    instance = CompositeModel(org_id=10, user_id=42, role="admin")
    assert instance.identity_values == (10, 42)
    assert instance.identity_dict == {"org_id": 10, "user_id": 42}

def test_configured_id_identity():
    identity = ID("507f1f77bcf86cd799439011")
    assert str(identity) == "507f1f77bcf86cd799439011"
    assert isinstance(identity, ID)

    class MongoDoc(Model):
        _id: ID = Field(database=DatabaseField(primary_key=True, default_factory=ID))
        name: str

    meta = MongoDoc.metadata()
    assert meta.identity.kind == IdentityKind.ID
    assert meta.primary_key_field == "_id"

    doc = MongoDoc(_id=identity, name="Document A")
    assert doc.identity_values == identity

def test_default_auto_synthesized_identity():
    class BareModel(Model):
        name: str

    meta = BareModel.metadata()
    assert "id" in meta.fields
    assert meta.fields["id"].primary_key is True
    assert meta.identity.kind == IdentityKind.INTEGER
    assert meta.identity.generated is True

class Article(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    title: str
    views: int = 0
    pinned: bool = False

def test_lifecycle_transitions():
    article = Article(title="First Draft", views=0)

    assert article.state == Lifecycle.NEW
    assert article.is_new is True
    assert article.is_persisted is False
    assert article.is_dirty is False

    article._mark_persisted()
    assert article.state == Lifecycle.PERSISTED
    assert article.is_new is False
    assert article.is_persisted is True
    assert article.is_dirty is False
    assert article.dirty_fields == set()

    article.title = "Published Title"
    assert article.state == Lifecycle.DIRTY
    assert article.is_dirty is True
    assert article.dirty_fields == {"title"}
    assert article.get_dirty_changes() == {"title": ("First Draft", "Published Title")}

    article.title = "First Draft"
    assert article.is_dirty is False
    assert article.state == Lifecycle.PERSISTED
    assert article.dirty_fields == set()

    article.title = "New Title"
    article.views = 100
    assert article.dirty_fields == {"title", "views"}
    assert article.get_dirty_changes() == {
        "title": ("First Draft", "New Title"),
        "views": (0, 100),
    }

    article._mark_persisted()
    assert article.state == Lifecycle.PERSISTED
    assert article.is_dirty is False
    assert article.dirty_fields == set()

    article._mark_deleted()
    assert article.state == Lifecycle.DELETED

    article._mark_detached()
    assert article.state == Lifecycle.DETACHED

def test_immutable_field_enforcement():
    class ImmutableRecord(Model):
        id: int = Field(database=DatabaseField(primary_key=True))
        account_number: str = Field(database=DatabaseField(immutable=True))
        balance: int = 0

    record = ImmutableRecord(id=1, account_number="ACC-100", balance=500)

    record.account_number = "ACC-200"

    record._mark_persisted()
    with pytest.raises(ValidationError):
        record.account_number = "ACC-999"

    record.balance = 600
    assert record.balance == 600
    assert record.is_dirty is True

class Product(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    sku: str
    price: float

    class Meta:
        timestamps = True
        soft_delete = True

def test_timestamps_and_soft_delete():
    meta = Product.metadata()
    assert meta.timestamps is True
    assert meta.soft_delete is True
    assert "created_at" in meta.fields
    assert "updated_at" in meta.fields
    assert "deleted_at" in meta.fields
    assert "is_deleted" in meta.fields

    prod = Product(sku="ITEM-1", price=19.99)
    assert isinstance(prod.created_at, datetime)
    assert prod.created_at.tzinfo == timezone.utc
    assert isinstance(prod.updated_at, datetime)
    assert prod.updated_at.tzinfo == timezone.utc
    assert prod.deleted_at is None
    assert prod.is_deleted is False

    prod.soft_delete()
    assert prod.is_deleted is True
    assert isinstance(prod.deleted_at, datetime)
    assert prod.state == Lifecycle.DELETED

    prod.restore()
    assert prod.is_deleted is False
    assert prod.deleted_at is None
    assert prod.state == Lifecycle.DIRTY

class Address(Model):
    street: str
    city: str

class OrderItem(Model):
    product_name: str
    quantity: int
    price: float

class Post(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    title: str
    user_id: int = Field(database=DatabaseField(foreign_key="users.id"))

class Profile(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    bio: str
    user_id: int

class Role(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    name: str

class Customer(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str

    address: Address = Embedded(Address)
    items: list[OrderItem] = EmbeddedMany(OrderItem)

    profile: Profile = OneToOne(Profile, foreign_key="user_id")
    posts: list[Post] = OneToMany(Post, foreign_key="user_id")
    roles: list[Role] = ManyToMany(Role, through="customer_roles")

def test_relationship_metadata():
    meta = Customer.metadata()
    assert len(meta.relationships) == 5

    r_address = meta.relationships["address"]
    assert r_address.kind == RelationshipKind.EMBEDDED_ONE
    assert r_address.is_embedded is True
    assert not r_address.is_collection
    assert isinstance(r_address, RelationshipMetadata)

    r_items = meta.relationships["items"]
    assert r_items.kind == RelationshipKind.EMBEDDED_MANY
    assert r_items.is_embedded is True
    assert r_items.is_collection is True

    r_profile = meta.relationships["profile"]
    assert r_profile.kind == RelationshipKind.ONE_TO_ONE
    assert r_profile.foreign_key == "user_id"

    r_posts = meta.relationships["posts"]
    assert r_posts.kind == RelationshipKind.ONE_TO_MANY
    assert r_posts.is_collection is True

    r_roles = meta.relationships["roles"]
    assert r_roles.kind == RelationshipKind.MANY_TO_MANY
    assert r_roles.through == "customer_roles"

def test_reference_and_many_to_one_and_embedded_one():
    assert EmbeddedOne is Embedded

    class Department(Model):
        id: int = Field(database=DatabaseField(primary_key=True))
        name: str

    class Employee(Model):
        id: int = Field(database=DatabaseField(primary_key=True))
        dept_id: int
        department: Department = ManyToOne(Department, foreign_key="dept_id")
        ref_doc: Department = Reference(Department, foreign_key="dept_id")
        badge: Department = EmbeddedOne(Department)

    meta = Employee.metadata()
    assert isinstance(meta.identity, IdentityMetadata)
    assert isinstance(meta.fields["id"], FieldMetadata)

    r_dept = meta.relationships["department"]
    assert r_dept.kind == RelationshipKind.MANY_TO_ONE
    assert not r_dept.is_collection

    r_ref = meta.relationships["ref_doc"]
    assert r_ref.kind == RelationshipKind.REFERENCE

    r_badge = meta.relationships["badge"]
    assert r_badge.kind == RelationshipKind.EMBEDDED_ONE
    assert r_badge.is_embedded is True

def test_embedded_model_instance_interaction():
    cust = Customer(
        name="Alice",
        address=Address(street="123 Main St", city="Metropolis"),
        items=[OrderItem(product_name="Gadget", quantity=2, price=9.99)],
    )

    assert cust.address.city == "Metropolis"
    assert len(cust.items) == 1
    assert cust.items[0].product_name == "Gadget"

    d = cust.to_dict()
    assert d["name"] == "Alice"
    assert d["address"]["city"] == "Metropolis"
    assert d["items"][0]["quantity"] == 2

def test_query_ast_path_integration():

    assert isinstance(Customer.name, Path)
    assert str(Customer.name) == "name"

    cond1 = Customer.name == "Alice"
    assert cond1.operator == Operator.EQ
    assert cond1.value == "Alice"
    assert cond1.path == Customer.name

    cond2 = Customer.id >= 18
    assert cond2.operator == Operator.GE
    assert cond2.value == 18

    comb = (Customer.id >= 18) & (Customer.name == "Alice")
    assert comb.operator == Operator.AND
    assert len(comb.children) == 2

    assert (Customer.id.in_([1, 2, 3])).operator == Operator.IN
    assert (Customer.name.like("Al%")).operator == Operator.LIKE
    assert (Customer.name.regex(r"^Al.*")).operator == Operator.REGEX
    assert (Customer.id.between(1, 10)).operator == Operator.BETWEEN
    assert (Customer.name.is_null()).operator == Operator.IS_NULL

    assert isinstance(Customer.address.city, Path)
    assert str(Customer.address.city) == "address.city"
    nested_cond = Customer.address.city == "Springfield"
    assert nested_cond.value == "Springfield"
    assert str(nested_cond.path) == "address.city"

    asc_ord = Customer.name.asc()
    assert not asc_ord.descending
    assert asc_ord.path == Customer.name

    desc_ord = Customer.name.desc()
    assert desc_ord.descending
    assert desc_ord.path == Customer.name

class IndexedModel(Model):
    id: int = Field(database=DatabaseField(primary_key=True))
    dept: str
    code: str

    class Meta:
        indexes = (Index("dept", "code", unique=True, name="idx_dept_code"),)
        constraints = (
            UniqueConstraint("dept", "code", name="uq_dept_code"),
            CheckConstraint("id > 0", name="chk_positive_id"),
            ForeignKeyConstraint(
                fields=("dept",),
                reference_table="departments",
                reference_fields=("id",),
                name="fk_dept",
            ),
        )

def test_declarative_indexes_and_constraints():
    meta = IndexedModel.metadata()
    assert len(meta.indexes) == 1
    idx = meta.indexes[0]
    assert idx.fields == ("dept", "code")
    assert idx.unique is True
    assert idx.name == "idx_dept_code"

    assert len(meta.constraints) == 3
    assert any(isinstance(c, UniqueConstraint) for c in meta.constraints)
    assert any(isinstance(c, CheckConstraint) for c in meta.constraints)
    assert any(isinstance(c, ForeignKeyConstraint) for c in meta.constraints)

def test_relationship_forward_reference_resolution():
    class ParentModel(Model):
        id: int = Field(database=DatabaseField(primary_key=True))
        children: list[ChildModel] = OneToMany("ChildModel", foreign_key="parent_id")

    class ChildModel(Model):
        id: int = Field(database=DatabaseField(primary_key=True))
        parent_id: int

    meta = ParentModel.metadata()
    rel = meta.relationships["children"]
    assert rel.target == "ChildModel"

    from renus.db.models.base import _MODEL_REGISTRY

    resolved = rel.resolve_target(_MODEL_REGISTRY)
    assert resolved is ChildModel

def test_soft_delete_disabled_error():
    class HardDeleteOnly(Model):
        id: int = Field(database=DatabaseField(primary_key=True))
        name: str

    item = HardDeleteOnly(id=1, name="Temp")
    with pytest.raises(ValueError, match="does not have soft_delete enabled"):
        item.soft_delete()

    with pytest.raises(ValueError, match="does not have soft_delete enabled"):
        item.restore()

def test_composite_primary_key_field_error():
    class MultiPK(Model):
        k1: int = Field(database=DatabaseField(primary_key=True))
        k2: str = Field(database=DatabaseField(primary_key=True))

    meta = MultiPK.metadata()
    with pytest.raises(ValueError, match="composite primary key"):
        _ = meta.primary_key_field

def test_field_persistence_bundle():
    f = Field(database=DatabaseField(column_name="c_name", unique=True, indexed=True, immutable=True))
    assert f.database.column_name == "c_name"
    assert f.database.unique is True
    assert f.database.indexed is True
    assert f.database.immutable is True

def test_model_dict_and_to_dict_parity():
    cust = Customer(
        name="Bob",
        address=Address(street="456 Elm St", city="Gotham"),
    )
    d1 = cust.to_dict()
    d2 = cust.dict()
    assert d1 == d2
    assert d1["name"] == "Bob"
    assert d1["address"]["street"] == "456 Elm St"
