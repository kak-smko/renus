"""End-to-end tests mixing the fluent query builder with the repository.

These tests exercise the repository + query API against every available
adapter using four distinct datasets ("scenarios"). Each scenario runs the same
full checklist of operations so behaviour is verified against varying data sizes.

Operations covered:
    create, save, get/where().first(), update,
    limit, skip (offset), count, count with limit/skip,
    count with/without soft-deleted rows, paginate,
    include with filter, group_by, order_by + limit, select.
"""

from __future__ import annotations

import pytest

from renus.db import (
    Count,
    Database,
    DatabaseField,
    Field,
    Include,
    OneToMany,
    Model,
)
from tests.db._conformance import (
    adapter_for,
    cleanup,
    conformance_tests,
    database_for,
)


class Post(Model):
    """A post owned by a user (one-to-many target)."""

    id: str = Field(database=DatabaseField(primary_key=True))
    title: str
    user_id: str = ""


class User(Model):
    """The primary model under test."""

    id: str = Field(database=DatabaseField(primary_key=True))
    username: str = Field(database=DatabaseField(unique=True))
    name: str | None = None
    age: int = 0
    active: bool = True
    posts: list[Post] = OneToMany(
        Post, foreign_key="user_id", on_save="cascade", on_delete="cascade"
    )


class SoftUser(Model):
    """A soft-deletable model used for deleted-count checks."""

    id: str = Field(database=DatabaseField(primary_key=True))
    username: str

    class Meta:
        soft_delete = True
        timestamps = True


ADAPTERS = conformance_tests()



async def _seed(db: Database, rows: list[dict]) -> object:
    """Create users (and any nested posts) and return the user repository."""
    u_repo = db.repository(User)
    for row in rows:
        username = row["username"]
        await u_repo.create(
            User(
                id=f"user-{username}",
                username=username,
                name=row.get("name"),
                age=row.get("age", 0),
                active=row.get("active", True),
                posts=[
                    Post(id=f"{username}-post-{index}", title=title)
                    for index, title in enumerate(row.get("posts", []))
                ],
            )
        )
    return u_repo


async def _full_checklist(
    db: Database,
    u_repo: object,
    total: int,
    active: int,
) -> None:
    """Run every operation against the current dataset and assert invariants."""
    model = u_repo.model
    s_repo = db.repository(SoftUser)

    # --- create -----------------------------------------------------------
    created = await u_repo.create(
        User(id="user-zz_new", username="zz_new", name="New", age=10, active=True)
    )
    assert created.id is not None
    assert created.is_persisted() is True
    total += 1
    active += 1

    # --- save (create-then-update on a single instance) -------------------
    obj = User(id="user-zz_saved", username="zz_saved", name="First", age=5, active=True)
    await u_repo.save(obj)
    assert obj.is_persisted() is True
    obj.name = "Second"
    obj.age = 6
    await u_repo.save(obj)
    assert obj.is_dirty() is False
    saved = await u_repo.where(User.username == "zz_saved").first()
    assert saved is not None
    assert saved.name == "Second"
    assert saved.age == 6
    total += 1
    active += 1

    # --- get / where().first() --------------------------------------------
    fetched = await u_repo.where(User.username == "zz_saved").first()
    assert fetched is not None
    assert fetched.username == "zz_saved"
    assert await u_repo.where(User.username == "does_not_exist").first() is None

    # --- update -----------------------------------------------------------
    rows = await u_repo.where(User.username == "zz_new").update({"age": 123})
    assert rows == 1
    refetched = await u_repo.where(User.username == "zz_new").first()
    assert refetched is not None
    assert refetched.age == 123


    # --- limit / skip (offset) --------------------------------------------
    ordered = await u_repo.query().order_by(User.username.asc()).all()
    limited = await u_repo.query().order_by(User.username.asc()).limit(3).all()
    assert len(limited) == min(3, len(ordered))
    assert limited[0].username == ordered[0].username

    skipped = await u_repo.query().order_by(User.username.asc()).offset(1).all()
    assert len(skipped) == len(ordered) - 1
    assert skipped[0].username == ordered[1].username

    limit_skip = await u_repo.query().order_by(User.username.asc()).offset(1).limit(2).all()
    assert len(limit_skip) == min(2, max(0, len(ordered) - 1))
    assert [r.username for r in limit_skip] == [o.username for o in ordered[1 : 1 + 2]]

    # --- count ------------------------------------------------------------
    assert await u_repo.query().count() == total
    assert await u_repo.query(User.active == True).count() == active

    # --- count with limit/skip (count ignores limit/offset) ----------------
    assert (
        await u_repo.query().order_by(User.username.asc()).offset(1).limit(2).count()
        == total
    )

    # --- paginate ----------------------------------------------------------
    size = 2
    page1 = await u_repo.query().order_by(User.username.asc()).paginate(1, size).all()
    page2 = await u_repo.query().order_by(User.username.asc()).paginate(2, size).all()
    assert [row.username for row in page1] == [
        row.username for row in ordered[:size]
    ]
    assert [row.username for row in page2] == [
        row.username for row in ordered[size : size * 2]
    ]

    # --- include with filter ----------------------------------------------
    initial_total = total - 2
    loaded = await u_repo.query(User.username == "aa_home").include(
        Include(User.posts, filter=Post.title == "keep")
    ).all()
    if initial_total == 0:
        assert loaded == []
    else:
        assert len(loaded) == 1
        assert loaded[0].username == "aa_home"
        assert [post.title for post in loaded[0].posts] == ["keep"]

    # --- group_by (returns plain dict rows) --------------------------------
    groups = (
        await u_repo.query()
        .group_by(User.active)
        .aggregate(n=Count(User.id))
        .all()
    )
    by_active = {g["active"]: g["n"] for g in groups}
    assert by_active[True] == active
    assert sum(by_active.values()) == total

    # --- order_by + limit ---------------------------------------------------
    top3 = await u_repo.query().order_by(User.username.asc()).limit(3).all()
    assert [r.username for r in top3] == [o.username for o in ordered[:3]]
    desc = await u_repo.query().order_by(User.username.desc()).limit(3).all()
    assert desc[0].username == ordered[-1].username

    # --- select (returns plain dict rows) ----------------------------------
    sel = await u_repo.query().select(User.id, User.username).all()
    assert all(isinstance(r, dict) for r in sel)
    assert {r["username"] for r in sel} == {o.username for o in ordered}

    # --- soft-delete counts ------------------------------------------------
    s1 = await s_repo.create(SoftUser(id="soft-sd1", username="sd1"))
    s2 = await s_repo.create(SoftUser(id="soft-sd2", username="sd2"))
    await s_repo.delete(s1)  # s1 soft-deleted

    assert await s_repo.query().count() == 1  # without deleted
    assert await s_repo.query().with_deleted().count() == 2  # with deleted
    assert await s_repo.query().only_deleted().count() == 1
    assert await s_repo.query().only_deleted().first() is not None
    deleted_only = await s_repo.query().only_deleted().first()
    assert deleted_only is not None
    assert deleted_only.username == "sd1"
    assert s2.username == "sd2"


# ---------------------------------------------------------------------------
# Five scenarios, each with a distinct dataset.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_mixed_operations_scenario_empty(kind: str):
    """Scenario 1: start empty, build the whole dataset through the API."""
    db = await database_for(kind, [User, Post, SoftUser])
    try:
        repo = db.repository(User)
        await _full_checklist(db, repo, total=0, active=0)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_mixed_operations_scenario_single(kind: str):
    """Scenario 2: one pre-seeded home user."""
    db = await database_for(kind, [User, Post, SoftUser])
    try:
        repo = await _seed(
            db,
            [
                {"username": "aa_home", "name": "Home", "age": 30, "active": True,
                 "posts": ["keep", "drop"]},
            ],
        )
        await _full_checklist(db, repo, total=1, active=1)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_mixed_operations_scenario_three(kind: str):
    """Scenario 3: three pre-seeded users."""
    db = await database_for(kind, [User, Post, SoftUser])
    try:
        repo = await _seed(
            db,
            [
                {"username": "aa_home", "name": "Alpha", "age": 31, "active": True,
                 "posts": ["keep"]},
                {"username": "bb_free", "name": "Bravo", "age": 22, "active": True},
                {"username": "cc_away", "name": "Charlie", "age": 55, "active": False},
            ],
        )
        await _full_checklist(db, repo, total=3, active=2)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_mixed_operations_scenario_five(kind: str):
    """Scenario 4: five pre-seeded users."""
    db = await database_for(kind, [User, Post, SoftUser])
    try:
        repo = await _seed(
            db,
            [
                {"username": "aa_home", "name": "Alpha", "age": 31, "active": True,
                 "posts": ["keep", "drop", "note"]},
                {"username": "bb_free", "name": "Bravo", "age": 22, "active": True,
                    "posts": ["keep", "drop", "note"]},
                {"username": "cc_away", "name": "Charlie", "age": 55, "active": False},
                {"username": "dd_cool", "name": "Delta", "age": 28, "active": True},
                {"username": "ee_quiet", "name": "Echo", "age": 40, "active": False},
            ],
        )
        await _full_checklist(db, repo, total=5, active=3)
    finally:
        await cleanup(db)

