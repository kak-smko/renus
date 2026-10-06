from __future__ import annotations

from datetime import date, datetime
import pytest

from renus.db import Embedded, EmbeddedMany, EmbeddedOne, Field, Model, ValidationError
from renus.db.validation.base import Rule
from renus.db.validation import (
    Email,
    In,
    Len,
    Max,
    MaxLen,
    Min,
    MinLen,
    Regex,
    Required,
    Validate,
)

class CustomUsernameRule(Rule):
    def __call__(self, value: str) -> str:
        return value.strip().lower()

    def json_schema(self):
        return {}


class Address(Model):
    street: str
    city: str
    country: str = "Test"
    postal_code: str | None = None

class User(Model):
    id: int
    username: str = Field(CustomUsernameRule(), MinLen(3), MaxLen(50))
    email: str = Field(Email("gmail"))
    age: int = Field(Min(18), Max(120))

    is_active: bool = Field(default=True)
    birth_date: date | None 

    address:Address

def test_user_model_creation_and_dict_conversion():
    user = User(
        id=1,
        username="  JohnDoe  ",
        email="john@example.com",
        age=25,
        address={
            "street": "123 Main Street",
            "city": "tee",
        },
    )

    assert str(user).startswith("User(")

    assert user.username == "johndoe"
    assert user.email == "john@example.com"
    assert user.age == 25

    assert isinstance(user.address, Address)
    assert user.address.city == "tee"
    assert user.address.street == "123 Main Street"
    assert user.address.country == "Test"
    assert user.address.postal_code is None

    assert user.is_active is True
    assert user.birth_date is None

    user_dict = dict(user)
    assert user_dict == {
        "id": 1,
        "username": "johndoe",
        "email": "john@example.com",
        "age": 25,
        "is_active": True,
        "birth_date": None,
        "address": {
            "street": "123 Main Street",
            "city": "tee",
            "country": "Test",
            "postal_code": None,
            "id": None,
        },
    }

    assert user.to_dict() == user_dict
    assert user.dict() == user_dict

def test_validation_error_on_invalid_user_data():
    with pytest.raises(ValidationError) as exc_info:
        User(
            id=1,
            username="ab",
            email="not-an-email",
            age=15,
            address={
                "street": "123 Main Street",
                "city": "Baku",
            },
        )

    err = exc_info.value
    assert "username" in err.errors
    assert "email" in err.errors
    assert "age" in err.errors
    assert "Validation failed:" in str(err)

def test_user_constructor_validates_dict():
    user = User({
        "id": 1,
        "username": "  JohnDoe  ",
        "email": "john@example.com",
        "age": 25,
        "address": {"street": "123 Main Street", "city": "Baku"},
    })
    assert user.id == 1
    assert user.username == "johndoe"
    assert user.email == "john@example.com"
    assert user.address.city == "Baku"

    user_from_dict = User({
        "id": 2,
        "username": "Alice",
        "email": "alice@example.com",
        "age": 30,
        "address": {"street": "Center 1", "city": "Baku"},
    })
    assert user_from_dict.id == 2
    assert user_from_dict.username == "alice"

def test_updating_a_model_with_runtime_validation():
    user = User(
        id=1,
        username="  JohnDoe  ",
        email="john@example.com",
        age=25,
        address={
            "street": "123 Main Street",
            "city": "Baku",
        },
    )

    user.age = 35
    assert user.age == 35

    with pytest.raises(ValidationError) as exc_info:
        user.age = 10
    assert "age" in exc_info.value.errors

    assert user.age == 35

    user.username = "  SuperAdmin  "
    assert user.username == "superadmin"

    with pytest.raises(ValidationError) as exc_info:
        user.username = "x"
    assert "username" in exc_info.value.errors

def test_nested_models_simple():
    class SimpleAddress(Model):
        street: str
        city: str

    class SimpleUser(Model):
        id: int
        username: str
        email: str
        age: int
        address: SimpleAddress

    user = SimpleUser(
        id=1,
        username="Bob",
        email="bob@example.com",
        age=40,
        address={
            "street": "Some Street",
            "city": "Baku",
        },
    )

    assert isinstance(user.address, SimpleAddress)
    assert user.address.street == "Some Street"
    assert user.address.city == "Baku"
    assert dict(user)["address"] == {"street": "Some Street", "city": "Baku", "id": None}

def test_field_keyword_validator():
    class NormalizeHandle(Rule):
        def __call__(self, value):
            return value.strip().lower()

        def json_schema(self):
            return {}

    class Profile(Model):
        handle: str = Field(MinLen(3), validator=NormalizeHandle())

    p = Profile(handle="  CoolGuy  ")
    assert p.handle == "coolguy"

    with pytest.raises(ValidationError):
        Profile(handle="hi")

def test_field_constraints():
    class Product(Model):
        title: str = Field(MinLen(2), MaxLen(10))
        price: float = Field(Min(0.01), Max(1000.0))
        category: str = Field(In("books", "electronics"))
        sku: str = Field(Regex(r"^[A-Z]{3}-\d{3}$"))

    p = Product(title="Laptop", price=999.99, category="electronics", sku="ABC-123")
    assert p.title == "Laptop"

    with pytest.raises(ValidationError) as exc_info:
        Product(title="A", price=-5, category="groceries", sku="invalid")

    err = exc_info.value.errors
    assert "title" in err
    assert "price" in err
    assert "category" in err
    assert "sku" in err

def test_nested_list_of_models():
    class Item(Model):
        name: str
        quantity: int

    class Order(Model):
        id: int
        items: list[Item]

    order = Order(id=100, items=[{"name": "Apple", "quantity": 3}, {"name": "Banana", "quantity": 5}])
    assert len(order.items) == 2
    assert isinstance(order.items[0], Item)
    assert order.items[0].name == "Apple"

    order_dict = dict(order)
    assert order_dict["items"] == [
        {"name": "Apple", "quantity": 3, "id": None},
        {"name": "Banana", "quantity": 5, "id": None},
    ]


def test_embedded_relationship_validation_rules():
    class Contact(Model):
        name: str
        city: str

    class Customer(Model):
        contact: Contact = EmbeddedOne(
            Contact, MinLen(2), description="Primary contact", widget="contact-card"
        )
        contacts: list[Contact] = EmbeddedMany(
            Contact, MinLen(1), MaxLen(2), description="Other contacts", widget="contact-list"
        )

    assert Customer.__db_metadata__.relationships["contact"].target is Contact
    assert Customer.__dict__["contact"].extra["widget"] == "contact-card"
    assert Customer._model_fields["contact"].field.description == "Primary contact"
    assert Customer.__dict__["contacts"].extra["widget"] == "contact-list"
    assert Customer._model_fields["contacts"].field.description == "Other contacts"

    customer = Customer(
        contact={"name": "Ada", "city": "London"},
        contacts=[{"name": "Grace", "city": "Arlington"}],
    )
    assert isinstance(customer.contact, Contact)
    assert customer.contact.city == "London"
    assert isinstance(customer.contacts[0], Contact)

    with pytest.raises(ValidationError) as exc_info:
        Customer(
            contact={"name": "Ada"},
            contacts=[
                {"name": "Grace", "city": "Arlington"},
                {"name": "Lin", "city": "Beijing"},
                {"name": "Margaret", "city": "Hampton"},
            ],
        )
    assert "contact" in exc_info.value.errors
    assert "contacts" in exc_info.value.errors

    with pytest.raises(ValidationError) as exc_info:
        customer.contacts = []
    assert "contacts" in exc_info.value.errors

def test_model_dict_access_and_membership():
    user = User(
        id=1,
        username="John",
        email="john@example.com",
        age=25,
        address={"street": "Main", "city": "Baku"},
    )

    assert user["id"] == 1
    assert user["username"] == "john"
    with pytest.raises(KeyError):
        _ = user["non_existent"]

    user["age"] = 26
    assert user.age == 26

    assert "id" in user
    assert "non_existent" not in user

def test_model_equality():
    u1 = User(id=1, username="John", email="john@example.com", age=25, address={"street": "Main", "city": "Baku"})
    u2 = User(id=1, username="John", email="john@example.com", age=25, address={"street": "Main", "city": "Baku"})
    assert u1 == u2
    assert u1 == dict(u2)

def test_legacy_validate_rules_still_works():
    form = {"username": "admin", "age": 25}
    rules = {
        "username": [Required],
    }
    v = Validate(form)
    res = v.rules(rules)
    assert res == {"username": "admin"}

def test_email_with_domain_restrictions():
    class RestrictedUser(Model):
        email: str = Field(Email(["gmail.com", "google.com"]))

    u = RestrictedUser(email="test@gmail.com")
    assert u.email == "test@gmail.com"

    with pytest.raises(ValidationError):
        RestrictedUser(email="test@yahoo.com")

def test_required_derived_from_type_optionality():

    user = User(
        username="John",
        email="john@example.com",
        age=25,
        address={"street": "Main St", "city": "Baku"},
    )
    assert user.id is None

    with pytest.raises(ValidationError) as exc_info:
        User(
            id=1,
            email="john@example.com",
            age=25,
            address={"street": "Main St", "city": "Baku"},
        )
    assert "username" in exc_info.value.errors

    with pytest.raises(ValidationError) as exc_info:
        User(
            id=1,
            username="John",
            email="john@example.com",
            age=25,
        )
    assert "address" in exc_info.value.errors

    user = User(
        id=1,
        username="John",
        email="john@example.com",
        age=25,
        address={"street": "Main St", "city": "Baku"},
    )
    assert user.birth_date is None
    assert user.is_active is True
    assert user.address.country == "Test"

    user.birth_date = None
    assert user.birth_date is None

class RequiredModel(Model):
    alpha: int
    beta: int | None = None
    gamma: str = "fallback"

def test_required_flags_with_defaults_and_nullable():
    fields = RequiredModel._model_fields
    assert fields["alpha"].required is True
    assert fields["beta"].required is False
    assert fields["gamma"].required is False

def test_field_has_no_required_parameter():

    import inspect

    sig = inspect.signature(Field.__init__)
    assert "required" not in sig.parameters

def test_field_numeric_comparison_constraints():
    class Stats(Model):
        a: int = Field(Min(1))
        b: int = Field(Min(10))
        c: int = Field(Max(99))
        d: int = Field(Max(50))

    s = Stats(a=1, b=10, c=99, d=50)
    assert (s.a, s.b, s.c, s.d) == (1, 10, 99, 50)

    with pytest.raises(ValidationError) as exc_info:
        Stats(a=0, b=9, c=100, d=51)
    errors = exc_info.value.errors
    assert "a" in errors
    assert "b" in errors
    assert "c" in errors
    assert "d" in errors

def test_field_max_digits_and_decimal_places():
    class Money(Model):
        amount: float = Field(Min(0))

    ok = Money(amount=123.45)
    assert ok.amount == 123.45

    with pytest.raises(ValidationError):
        Money(amount=-1)

def test_field_custom_error_template():
    class Score(Model):
        value: int = Field(Min(10), error="{0} error {1} msg {2}.")

    with pytest.raises(ValidationError) as exc:
        Score(value=5)
    assert "greater than or equal to 10" in exc.value.errors["value"][0]

def test_field_uses_callable_rules():
    import inspect

    params = inspect.signature(Field.__init__).parameters
    assert "min_length" not in params
    assert "gt" not in params
    assert "max_digits" not in params
    assert "error" in params
