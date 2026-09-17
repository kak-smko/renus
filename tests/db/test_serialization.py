from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

import pytest

from renus.db import (
    DatabaseField,
    Field,
    ID,
    Model,
    ValidationError,
    from_dict,
    from_json,
    sanitize_params,
    to_dict,
    to_json,
)


class RoleEnum(Enum):
    ADMIN = "admin"
    USER = "user"

class SerializedAddress(Model):
    street: str
    city: str
    zip_code: str

class SerializedProfile(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    uid: UUID = Field(database=DatabaseField(default_factory=uuid4))
    username: str
    role: RoleEnum = RoleEnum.USER
    rating: Decimal = Decimal("4.95")
    bio: str | None = None
    created_at: datetime = Field(database=DatabaseField(default_factory=lambda: datetime.now(timezone.utc)))
    birth_date: date | None = None
    avatar_bytes: bytes = b"\x89PNG\r\n"
    address: SerializedAddress | None = None
    mongo_id: ID = Field(database=DatabaseField(default_factory=ID))

def test_to_dict_scalars_and_models():
    addr = SerializedAddress(street="123 Main St", city="Metropolis", zip_code="10001")
    u_id = UUID("12345678-1234-5678-1234-567812345678")
    m_id = ID("507f1f77bcf86cd799439011")
    fixed_time = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    fixed_date = date(1990, 5, 20)

    prof = SerializedProfile(
        id=1,
        uid=u_id,
        username="alice",
        role=RoleEnum.ADMIN,
        rating=Decimal("4.80"),
        bio=None,
        created_at=fixed_time,
        birth_date=fixed_date,
        address=addr,
        mongo_id=m_id,
    )

    d = to_dict(prof)
    assert d["id"] == 1
    assert d["uid"] == "12345678-1234-5678-1234-567812345678"
    assert d["username"] == "alice"
    assert d["role"] == "admin"
    assert d["rating"] == 4.80
    assert d["bio"] is None
    assert d["created_at"] == "2026-09-07T12:00:00+00:00"
    assert d["birth_date"] == "1990-05-20"
    assert d["mongo_id"] == "507f1f77bcf86cd799439011"
    assert d["address"]["street"] == "123 Main St"
    assert d["address"]["city"] == "Metropolis"
    assert d["address"]["zip_code"] == "10001"

def test_to_dict_filtering_options():
    addr = SerializedAddress(street="1st Ave", city="Gotham", zip_code="10002")
    prof = SerializedProfile(
        id=2,
        username="bob",
        bio=None,
        address=addr,
    )

    d_no_none = to_dict(prof, exclude_none=True)
    assert "bio" not in d_no_none
    assert "username" in d_no_none

    d_inc = to_dict(prof, include=["id", "username"])
    assert set(d_inc.keys()) == {"id", "username"}

    d_exc = to_dict(prof, exclude=["address", "avatar_bytes", "created_at"])
    assert "address" not in d_exc
    assert "avatar_bytes" not in d_exc
    assert "username" in d_exc

def test_from_dict_with_automatic_type_coercion():
    data = {
        "id": 10,
        "uid": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
        "username": "charlie",
        "role": "user",
        "rating": 4.5,
        "created_at": "2026-01-15T10:30:00",
        "birth_date": "1995-12-01",
        "mongo_id": "507f1f77bcf86cd799439011",
        "address": {
            "street": "456 Elm St",
            "city": "Star City",
            "zip_code": "90210",
        },
    }

    prof = from_dict(SerializedProfile, data, validate=True)
    assert isinstance(prof, SerializedProfile)
    assert prof.id == 10
    assert prof.uid == UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
    assert prof.username == "charlie"
    assert prof.birth_date == date(1995, 12, 1)
    assert prof.mongo_id == ID("507f1f77bcf86cd799439011")
    assert isinstance(prof.address, SerializedAddress)
    assert prof.address.city == "Star City"

def test_from_dict_validation_failure():

    bad_data = {
        "city": "Metropolis",
        "zip_code": "10001",
    }
    with pytest.raises(ValidationError):
        from_dict(SerializedAddress, bad_data, validate=True)

def test_json_roundtrip():
    addr = SerializedAddress(street="742 Evergreen Terrace", city="Springfield", zip_code="49007")
    prof = SerializedProfile(
        id=99,
        username="homer",
        address=addr,
    )

    json_str = to_json(prof)
    assert isinstance(json_str, str)
    assert "742 Evergreen Terrace" in json_str

    restored = from_json(SerializedProfile, json_str)
    assert isinstance(restored, SerializedProfile)
    assert restored.id == 99
    assert restored.username == "homer"
    assert restored.address is not None and restored.address.city == "Springfield"

class SensitiveUser(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    username: str
    email: str

    password: str = Field(sensitive=True)
    security_token: str | None = Field(default=None, sensitive=True)

def test_sensitive_fields_hidden_in_to_dict():
    user = SensitiveUser(
        id="u1",
        username="alice",
        email="alice@example.com",
        password="$2b$12$secret_hash_xyz",
        security_token="tok_abc123",
    )

    assert user.password == "***"
    assert user.security_token == "***"

    assert user.get_sensitive("password") == "$2b$12$secret_hash_xyz"
    assert user.get_sensitive("security_token") == "tok_abc123"

    d = to_dict(user)
    assert d["id"] == "u1"
    assert d["username"] == "alice"
    assert d["email"] == "alice@example.com"
    assert "password" not in d
    assert "security_token" not in d
    assert "$2b$12$secret_hash_xyz" not in str(d)

def test_to_dict_include_sensitive_true():
    user = SensitiveUser(
        id="u5",
        username="eve",
        email="eve@example.com",
        password="$2b$12$explicit_real_value",
        security_token="tok_nested_secret",
    )

    d = to_dict(user, include_sensitive=True)
    assert d["password"] == "$2b$12$explicit_real_value"
    assert d["security_token"] == "tok_nested_secret"
    assert d["username"] == "eve"

def test_sanitize_params_masks_sensitive_fields():
    user = SensitiveUser(
        id="p1",
        username="mallory",
        email="mallory@example.com",
        password="my_super_secret_password",
        security_token="bearer tok_secret",
    )

    masked = sanitize_params(user)
    assert masked["password"] == "***"
    assert masked["security_token"] == "***"
    assert masked["username"] == "mallory"
    assert "my_super_secret_password" not in repr(masked)

    assert user.password == "***"
    assert user.get_sensitive("password") == "my_super_secret_password"

def test_sensitive_fields_hidden_in_to_json():
    user = SensitiveUser(
        id="u2",
        username="bob",
        email="bob@example.com",
        password="$2b$12$another_secret",
    )

    json_str = to_json(user)
    assert "another_secret" not in json_str
    assert "password" not in json_str
    assert "bob@example.com" in json_str

def test_sensitive_fields_validate_and_roundtrip():

    direct = from_dict(
        SensitiveUser,
        {
            "id": "u4",
            "username": "dave",
            "email": "dave@example.com",
            "password": "$2b$12$explicit",
        },
    )
    assert direct.password == "***"
    assert direct.get_sensitive("password") == "$2b$12$explicit"

    assert "password" not in to_dict(direct)

    rt = from_dict(SensitiveUser, to_dict(direct, include_sensitive=True))
    assert rt.get_sensitive("password") == "$2b$12$explicit"
