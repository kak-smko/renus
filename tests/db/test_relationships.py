from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Embedded,
    EmbeddedMany,
    Field,
    OneToMany,
    OneToOne,
    ReModel,
    SQLiteAdapter,
)

from tests.db import _native_helpers as nh

class PostalAddress(ReModel):
    street: str
    city: str
    code:int=10

class LineItem(ReModel):
    name: str
    price: float
    qty: int

class Comment(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    body: str
    post_id: int = 0

class BlogPost(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    title: str
    author_id: int = 0
    comments: list[Comment] = OneToMany(Comment, foreign_key="post_id", cascade=("all",))

class Author(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str
    address: PostalAddress = Embedded(PostalAddress)
    tags: list[LineItem] = EmbeddedMany(LineItem)
    posts: list[BlogPost] = OneToMany(BlogPost, foreign_key="author_id", cascade=("all",))

class Profile(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    account_id: int = 0
    bio: str

class TagItem(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    account_id: int = 0
    label: str

class Account(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str
    profile: Profile = OneToOne(Profile, foreign_key="account_id", cascade=("all",))
    tags: list[TagItem] = OneToMany(TagItem, foreign_key="account_id", cascade=("all",))

@pytest.mark.asyncio
async def test_embedded_models_persistence_and_loading():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Author, BlogPost, Comment])

    author_repo = db.repository(Author)

    author = Author(
        name="Alice",
        address=PostalAddress(street="42 Galaxy Way", city="London"),
        tags=[
            LineItem(name="Tech", price=0.0, qty=1),
            LineItem(name="Python", price=0.0, qty=2),
        ],
    )
    await author_repo.create(author)
    assert author.id == 1

    loaded_authors = await author_repo.query().include(Author.address, Author.tags).all()
    assert len(loaded_authors) == 1
    loaded = loaded_authors[0]

    assert loaded.name == "Alice"
    assert loaded.address.street == "42 Galaxy Way"
    assert loaded.address.city == "London"
    assert loaded.address.code == 10
    assert len(loaded.tags) == 2
    assert loaded.tags[0].name == "Tech"
    assert loaded.tags[1].name == "Python"

    await db.disconnect()

@pytest.mark.asyncio
async def test_one_to_many_cascaded_save_and_selectin_loading():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Author, BlogPost, Comment])

    author_repo = db.repository(Author)
    post_repo = db.repository(BlogPost)

    a1 = Author(
        name="Bob",
        address=PostalAddress(street="1 St", city="NYC"),
        posts=[BlogPost(title="Post 1"), BlogPost(title="Post 2")],
    )
    a2 = Author(
        name="Charlie",
        address=PostalAddress(street="2 St", city="LA"),
        posts=[BlogPost(title="Post 3")],
    )

    await author_repo.create(a1)
    await author_repo.create(a2)

    all_posts = await post_repo.query().all()
    assert len(all_posts) == 3
    assert all_posts[0].author_id == a1.id
    assert all_posts[1].author_id == a1.id
    assert all_posts[2].author_id == a2.id

    authors = await author_repo.query().include(Author.posts).order_by(Author.name.asc()).all()
    assert len(authors) == 2

    bob = authors[0]
    assert bob.name == "Bob"
    assert len(bob.posts) == 2
    assert {p.title for p in bob.posts} == {"Post 1", "Post 2"}

    charlie = authors[1]
    assert charlie.name == "Charlie"
    assert len(charlie.posts) == 1
    assert charlie.posts[0].title == "Post 3"

    await db.disconnect()

@pytest.mark.asyncio
async def test_cascaded_deletion():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Author, BlogPost, Comment])

    author_repo = db.repository(Author)
    post_repo = db.repository(BlogPost)

    author = Author(
        name="Dave",
        address=PostalAddress(street="Main", city="Paris"),
        posts=[BlogPost(title="Dave's Thoughts")],
    )
    await author_repo.create(author)
    assert await post_repo.count(BlogPost.author_id == author.id) == 1

    await author_repo.delete(author)
    assert await author_repo.count(Author.id == author.id) == 0
    assert await post_repo.count(BlogPost.author_id == author.id) == 0

    await db.disconnect()

@pytest.mark.asyncio
async def test_one_to_one_and_many_relational_persistence_and_loading():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Account, Profile, TagItem])

    account_repo = db.repository(Account)
    profile_repo = db.repository(Profile)
    tag_repo = db.repository(TagItem)

    account = Account(
        name="Acme",
        profile=Profile(bio="A company"),
        tags=[TagItem(label="tech"), TagItem(label="b2b")],
    )
    await account_repo.create(account)
    assert account.id == 1

    profiles = await profile_repo.query().all()
    assert len(profiles) == 1
    assert profiles[0].account_id == account.id
    assert profiles[0].bio == "A company"

    tags = await tag_repo.query().order_by(TagItem.id.asc()).all()
    assert len(tags) == 2
    assert {t.account_id for t in tags} == {account.id}
    assert [t.label for t in tags] == ["tech", "b2b"]

    loaded = (await account_repo.query().include(Account.profile, Account.tags).all())[0]
    assert loaded.profile.bio == "A company"
    assert [t.label for t in loaded.tags] == ["tech", "b2b"]

    await account_repo.delete(account)
    assert await account_repo.count(Account.id == account.id) == 0
    assert await profile_repo.count(Profile.account_id == account.id) == 0
    assert await tag_repo.count(TagItem.account_id == account.id) == 0

    await db.disconnect()

class NativeAddress(ReModel):
    street: str

class NativeTag(ReModel):
    name: str

class NativeItem(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: NativeAddress = Embedded(NativeAddress)
    tags: list[NativeTag] = EmbeddedMany(NativeTag)

class NativeProfile(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    account_id: str = ""
    bio: str

class NativeTagItem(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    account_id: str = ""
    label: str

class NativeAccount(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    profile: NativeProfile = OneToOne(
        NativeProfile, foreign_key="account_id", cascade=("all",)
    )
    tags: list[NativeTagItem] = OneToMany(
        NativeTagItem, foreign_key="account_id", cascade=("all",)
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_stored_bytes_for_embedded_subtables(kind):
    db = await nh.connect_schema(kind, [NativeItem])
    try:
        repo = db.repository(NativeItem)
        await repo.create(
            NativeItem(
                id="n1",
                name="widget",
                address=NativeAddress(street="one"),
                tags=[NativeTag(name="a"), NativeTag(name="b")],
            )
        )

        (parent,) = await nh.native_all(db, "nativeitems")
        assert parent["name"] == "widget"

        (loaded,) = (
            await repo.query()
            .include(NativeItem.address)
            .include(NativeItem.tags)
            .all()
        )
        assert loaded.address.street == "one"
        assert [t.name for t in loaded.tags] == ["a", "b"]
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_stored_bytes_for_relational_persistence(kind):
    db = await nh.connect_schema(kind, [NativeAccount, NativeProfile, NativeTagItem])
    try:
        repo = db.repository(NativeAccount)
        await repo.create(
            NativeAccount(
                id="a1",
                name="Native ACME",
                profile=NativeProfile(id="p1", bio="raw bio"),
                tags=[NativeTagItem(id="t1", label="tech"), NativeTagItem(id="t2", label="b2b")],
            )
        )

        acct = (await nh.native_all(db, "nativeaccounts"))[0]
        assert acct["name"] == "Native ACME"
        assert "profile" not in acct
        assert "tags" not in acct

        profiles = await nh.native_all(db, "nativeprofiles")
        assert profiles[0]["bio"] == "raw bio"
        assert profiles[0]["account_id"] == "a1"

        tags = await nh.native_all(db, "nativetagitems")
        assert [t["label"] for t in tags] == ["tech", "b2b"]
        assert all(t["account_id"] == "a1" for t in tags)
    finally:
        await nh.cleanup(db)

class DocCountry(ReModel):
    name: str
    code:int

class DocTrans(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    key: str
    countries: list[DocCountry] = EmbeddedMany(DocCountry)
    trans: dict
    tags: list

async def _connect_db():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([DocTrans])
    return db

@pytest.mark.asyncio
async def test_bare_dict_list_auto_become_embedded():
    db = await _connect_db()
    try:
        meta = DocTrans.metadata()
        assert "trans" not in meta.fields
        assert "tags" not in meta.fields
        assert meta.relationships["trans"].kind.value == "embedded_one"
        assert meta.relationships["trans"].is_embedded
        assert meta.relationships["tags"].kind.value == "embedded_many"
        assert meta.relationships["tags"].is_embedded
        assert meta.relationships["tags"].is_collection
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_dict_list_round_trip_and_subqueries():
    db = await _connect_db()
    try:
        repo = db.repository(DocTrans)
        await repo.create(
            DocTrans(
                id="1",
                key="a",
                trans={"en": "one", "fa": "یک"},
                tags=["book", "pen", "3"],
                countries=[DocCountry(name="ir", code=10), DocCountry(name="us", code=1)],
            )
        )
        await repo.create(
            DocTrans(
                id="2",
                key="five",
                trans={"en": "5"},
                tags=["pen"],
                countries=[DocCountry(name="de", code=20)],
            )
        )

        objs = (
            await repo.query()
            .include(DocTrans.trans)
            .include(DocTrans.tags)
            .include(DocTrans.countries)
            .all()
        )
        by_id = {o.id: o for o in objs}

        assert by_id["1"].trans == {"en": "one", "fa": "یک"}
        assert by_id["1"].tags == ["book", "pen", "3"]
        assert [c.name for c in by_id["1"].countries] == ["ir", "us"]

        assert [o.id for o in await repo.query(DocTrans.trans.en == "one").all()] == ["1"]

        assert [o.id for o in await repo.query(DocTrans.tags.in_("book")).all()] == ["1"]

        assert sorted(o.id for o in await repo.query(DocTrans.tags.in_(["book", "z"])).all()) == ["1"]

        assert [o.id for o in await repo.query(DocTrans.tags == ["book", "pen"]).all()] == ["1"]

        assert [o.id for o in await repo.query(DocTrans.countries.name == "us").all()] == ["1"]
        assert [o.id for o in await repo.query(DocTrans.countries.code >= 10).all()] == ["1", "2"]
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_dict_list_reject_non_string_values():
    db = await _connect_db()
    repo = db.repository(DocTrans)

    with pytest.raises(TypeError, match="must be strings"):
        await repo.create(
            DocTrans(id="1", key="a", trans={"en": 5}, tags=[], countries=[])
        )

    with pytest.raises(TypeError, match="must be strings"):
        await repo.create(
            DocTrans(id="2", key="a", trans={1: "v"}, tags=[], countries=[])
        )

    with pytest.raises(TypeError, match="must be strings"):
        await repo.create(
            DocTrans(id="3", key="a", trans={}, tags=["book", 3], countries=[])
        )
