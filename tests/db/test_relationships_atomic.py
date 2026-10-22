from __future__ import annotations

import pytest

from renus.db import DatabaseField, Field, Model
from tests.db._conformance import cleanup, conformance_tests, database_for


class Addr(Model):
    city: str


class Tag(Model):
    label: str


class Item(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: Addr | None = None
    tags: list[Tag] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)


ADAPTERS = conformance_tests()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_fields_roundtrip_update_and_query(kind: str):
    db = await database_for(kind, [Item])
    try:
        repo = db.repository(Item)
        item = await repo.create(
            Item(
                id="item-1",
                name="book",
                address={"city": "Oslo"},
                tags=[{"label": "python"}, Tag(label="database")],
                attributes={"color": "blue"},
            )
        )

        assert isinstance(item.address, Addr)
        assert all(isinstance(tag, Tag) for tag in item.tags)

        loaded = await repo.where(Item.id == "item-1").first()
        assert loaded is not None
        assert loaded.address == Addr(city="Oslo")
        assert [tag.label for tag in loaded.tags] == ["python", "database"]
        assert loaded.attributes == {"color": "blue"}

        matching_address = await repo.where(Item.address.city == "Oslo").first()
        assert matching_address is not None
        assert matching_address.id == "item-1"
        matching_tag = await repo.where(Item.tags.any(Tag.label == "python")).first()
        assert matching_tag is not None
        assert matching_tag.id == "item-1"

        loaded.address = Addr(city="Helsinki")
        loaded.tags = [Tag(label="renus")]
        loaded.attributes = {"color": "green"}
        await repo.save(loaded)

        updated = await repo.where(Item.id == "item-1").first()
        assert updated is not None
        assert updated.address == Addr(city="Helsinki")
        assert [tag.label for tag in updated.tags] == ["renus"]
        assert updated.attributes == {"color": "green"}
    finally:
        await cleanup(db)
