from __future__ import annotations

import pytest

from renus.db import (
    DatabaseField,
    Embedded,
    EmbeddedMany,
    Field,
    LoadingStrategy,
    ManyToMany,
    ManyToOne,
    Model,
    OneToMany,
    OneToOne,
)
from tests.db._conformance import cleanup, conformance_tests, database_for


ADAPTERS = conformance_tests()


class JoinedDepartment(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str


class JoinedEmployee(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    department_id: str
    department: JoinedDepartment = ManyToOne(
        JoinedDepartment,
        foreign_key="department_id",
        loading="joined",
    )


class JoinedPost(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    title: str
    author_id: str


class JoinedAuthor(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    posts: list[JoinedPost] = OneToMany(
        JoinedPost,
        foreign_key="author_id",
        on_save="cascade",
        loading="joined",
    )


class JoinedAddress(Model):
    city: str


class JoinedTag(Model):
    label: str


class JoinedProfile(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    bio: str
    owner_id: str


class JoinedEmbeddedOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: JoinedAddress = Embedded(JoinedAddress, loading="joined")
    tags: list[JoinedTag] = EmbeddedMany(JoinedTag, loading="joined")


class JoinedProfileOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    profile: JoinedProfile = OneToOne(
        JoinedProfile,
        foreign_key="owner_id",
        on_save="cascade",
        loading="joined",
    )


class JoinedRole(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str


class JoinedRoleOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    roles: list[JoinedRole] = ManyToMany(
        JoinedRole,
        through="joined_role_owner_roles",
        on_save="cascade",
        loading="joined",
    )


class SelectinAddress(Model):
    city: str


class SelectinTag(Model):
    label: str


class SelectinEmbeddedOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: SelectinAddress = Embedded(
        SelectinAddress,
        loading=LoadingStrategy.LAZY,
    )
    tags: list[SelectinTag] = EmbeddedMany(
        SelectinTag,
        loading=LoadingStrategy.LAZY,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_joined_relationships_are_included_by_default(kind):
    db = await database_for(
        kind,
        [
            JoinedDepartment,
            JoinedEmployee,
            JoinedAuthor,
            JoinedPost,
            JoinedAddress,
            JoinedTag,
            JoinedEmbeddedOwner,
            JoinedProfile,
            JoinedProfileOwner,
            JoinedRole,
            JoinedRoleOwner,
        ],
    )
    try:

        department_repo = db.repository(JoinedDepartment)
        employee_repo = db.repository(JoinedEmployee)
        await department_repo.create(JoinedDepartment(id="d1", name="Engineering"))
        await employee_repo.create(
            JoinedEmployee(id="e1", name="Alice", department_id="d1")
        )

        employee = (await employee_repo.query().all())[0]
        assert employee.department is not None
        assert employee.department.name == "Engineering"

        author_repo = db.repository(JoinedAuthor)
        await author_repo.create(
            JoinedAuthor(
                id="a1",
                name="Alice",
                posts=[
                    JoinedPost(id="p1", title="First", author_id="a1"),
                    JoinedPost(id="p2", title="Second", author_id="a1"),
                ],
            )
        )

        author = (await author_repo.query().all())[0]
        assert [post.title for post in author.posts] == ["First", "Second"]

        embedded_repo = db.repository(JoinedEmbeddedOwner)
        await embedded_repo.create(
            JoinedEmbeddedOwner(
                id="eo1",
                name="Alice",
                address=JoinedAddress(city="Oslo"),
                tags=[JoinedTag(label="python"), JoinedTag(label="database")],
            )
        )

        embedded = (await embedded_repo.query().all())[0]
        assert embedded.address.city == "Oslo"
        assert [tag.label for tag in embedded.tags] == ["python", "database"]

        profile_owner_repo = db.repository(JoinedProfileOwner)
        await profile_owner_repo.create(
            JoinedProfileOwner(
                id="po1",
                name="Alice",
                profile=JoinedProfile(id="profile1", bio="Developer", owner_id="po1"),
            )
        )

        profile_owner = (await profile_owner_repo.query().all())[0]
        assert profile_owner.profile.bio == "Developer"

        role_repo = db.repository(JoinedRole)
        await role_repo.create_many(
            [JoinedRole(id="admin", name="Admin"), JoinedRole(id="editor", name="Editor")]
        )
        role_owner_repo = db.repository(JoinedRoleOwner)
        await role_owner_repo.create(
            JoinedRoleOwner(
                id="ro1",
                name="Alice",
                roles=[
                    JoinedRole(id="admin", name="Admin"),
                    JoinedRole(id="editor", name="Editor"),
                ],
            )
        )

        role_owner = (await role_owner_repo.query().all())[0]
        assert [role.name for role in role_owner.roles] == ["Admin", "Editor"]
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_selectin_embedded_relationships_are_not_loaded(kind):
    
    db = await database_for(kind, [SelectinEmbeddedOwner])
    try:
        repo = db.repository(SelectinEmbeddedOwner)
        await repo.create(
            SelectinEmbeddedOwner(
                id="seo1",
                name="Alice",
                address=SelectinAddress(city="Oslo"),
                tags=[SelectinTag(label="python"), SelectinTag(label="database")],
            )
        )

        owner = await repo.query().first()
        assert owner is not None
        assert owner.address is None
        assert owner.tags == []

        included = await repo.query().include(
            SelectinEmbeddedOwner.address,
            SelectinEmbeddedOwner.tags,
        ).first()
        assert included is not None
        assert included.address.city == "Oslo"
        assert [tag.label for tag in included.tags] == ["python", "database"]
    finally:
        await cleanup(db)
