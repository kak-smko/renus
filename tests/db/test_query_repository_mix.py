"""End-to-end tests mixing the fluent query builder with the repository.

These tests exercise the repository + query API against a real SQLite backend
using five distinct datasets ("scenarios"). Each scenario runs the same full
checklist of operations so behaviour is verified against varying data sizes.

Operations covered:
    create, save, get/where().first(), update, upsert,
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
    SQLiteAdapter,
)


class Post(Model):
    """A post owned by a user (one-to-many target)."""

    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    title: str
    user_id: int = 0


class User(Model):
    """The primary model under test."""

    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(database=DatabaseField(unique=True))
    name: str | None = None
    age: int = 0
    active: bool = True
    posts: list[Post] = OneToMany(
        Post, foreign_key="user_id", on_save="cascade", on_delete="cascade"
    )


class SoftUser(Model):
    """A soft-deletable model used for deleted-count checks."""

    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str

    class Meta:
        soft_delete = True
        timestamps = True


def _make_db() -> Database:
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    return db


async def _connect(db: Database) -> None:
    await db.connect()
    await db.create_schema([User, Post, SoftUser])


async def _seed(db: Database, rows: list[dict]) -> object:
    """Create users (and any nested posts) and return the user repository."""
    u_repo = db.repository(User)
    for row in rows:
        await u_repo.create(
            User(
                username=row["username"],
                name=row.get("name"),
                age=row.get("age", 0),
                active=row.get("active", True),
                posts=[Post(title=t) for t in row.get("posts", [])],
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
        User(username="zz_new", name="New", age=10, active=True)
    )
    assert created.id is not None
    assert created.is_persisted is True
    total += 1
    active += 1

    # --- save (create-then-update on a single instance) -------------------
    obj = User(username="zz_saved", name="First", age=5, active=True)
    await u_repo.save(obj)
    assert obj.is_persisted is True
    obj.name = "Second"
    obj.age = 6
    await u_repo.save(obj)
    assert obj.is_dirty is False
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

    # --- upsert -----------------------------------------------------------
    # WHERE on the unique username drives upsert conflict detection.
    up_rows = await u_repo.where(User.username == "zz_upsert").upsert(
        {"name": "FirstTry", "age": 1, "active": True}
    )
    assert up_rows == 1
    up_fetched = await u_repo.where(User.username == "zz_upsert").first()
    assert up_fetched is not None
    assert up_fetched.name == "FirstTry"
    total += 1
    active += 1

    # Existing row -> update branch.
    up_rows2 = await u_repo.where(User.username == "zz_upsert").upsert(
        {"age": 2}
    )
    assert up_rows2 == 1
    assert (await u_repo.where(User.username == "zz_upsert").first()).age == 2

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
    assert len(page1) == min(size, len(ordered))
    if len(ordered) > size:
        assert len(page2) == min(size, len(ordered) - size)
    assert page1[0].username == ordered[0].username

    # --- include with filter ----------------------------------------------
    loaded = await u_repo.query(User.username == "aa_home").include(
        Include(User.posts, filter=Post.title == "keep")
    ).all()
    if loaded:
        assert len(loaded) == 1
        for row in loaded:
            assert all(p.title == "keep" for p in row.posts)

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
    s1 = await s_repo.create(SoftUser(username="sd1"))
    s2 = await s_repo.create(SoftUser(username="sd2"))
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
async def test_mixed_operations_scenario_empty():
    """Scenario 1: start empty, build the whole dataset through the API."""
    db = _make_db()
    await _connect(db)
    try:
        repo = db.repository(User)
        await _full_checklist(db, repo, total=0, active=0)
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_mixed_operations_scenario_single():
    """Scenario 2: one pre-seeded home user."""
    db = _make_db()
    await _connect(db)
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
        await db.disconnect()


@pytest.mark.asyncio
async def test_mixed_operations_scenario_three():
    """Scenario 3: three pre-seeded users."""
    db = _make_db()
    await _connect(db)
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
        await db.disconnect()


@pytest.mark.asyncio
async def test_mixed_operations_scenario_five():
    """Scenario 4: five pre-seeded users."""
    db = _make_db()
    await _connect(db)
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
        await db.disconnect()

