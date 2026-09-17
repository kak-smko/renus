from __future__ import annotations

from renus.db import (
    DatabaseField,
    Field,
    ManyToMany,
    ManyToOne,
    Model,
    OneToMany,
    OneToOne,
)


def _id_field() -> Field:
    return Field(database=DatabaseField(primary_key=True))


class DeepOneToOne7(Model):
    id: str = _id_field()
    parent_id: str | None = None
    value: str = "one-to-one-7"


class DeepOneToOne6(Model):
    id: str = _id_field()
    parent_id: str | None = None
    child: DeepOneToOne7 = OneToOne(DeepOneToOne7, foreign_key="parent_id", on_save="cascade")


class DeepOneToOne5(Model):
    id: str = _id_field()
    parent_id: str | None = None
    child: DeepOneToOne6 = OneToOne(DeepOneToOne6, foreign_key="parent_id", on_save="cascade")


class DeepOneToOne4(Model):
    id: str = _id_field()
    parent_id: str | None = None
    child: DeepOneToOne5 = OneToOne(DeepOneToOne5, foreign_key="parent_id", on_save="cascade")


class DeepOneToOne3(Model):
    id: str = _id_field()
    parent_id: str | None = None
    child: DeepOneToOne4 = OneToOne(DeepOneToOne4, foreign_key="parent_id", on_save="cascade")


class DeepOneToOne2(Model):
    id: str = _id_field()
    parent_id: str | None = None
    child: DeepOneToOne3 = OneToOne(DeepOneToOne3, foreign_key="parent_id", on_save="cascade")


class DeepOneToOne1(Model):
    id: str = _id_field()
    child: DeepOneToOne2 = OneToOne(DeepOneToOne2, foreign_key="parent_id", on_save="cascade")


class DeepOneToMany7(Model):
    id: str = _id_field()
    value: str = "one-to-many-7"
    parent_id: str | None = None


class DeepOneToMany6(Model):
    id: str = _id_field()
    parent_id: str | None = None
    children: list[DeepOneToMany7] = OneToMany(
        DeepOneToMany7, foreign_key="parent_id", on_save="cascade"
    )


class DeepOneToMany5(Model):
    id: str = _id_field()
    parent_id: str | None = None
    children: list[DeepOneToMany6] = OneToMany(
        DeepOneToMany6, foreign_key="parent_id", on_save="cascade"
    )


class DeepOneToMany4(Model):
    id: str = _id_field()
    parent_id: str | None = None
    children: list[DeepOneToMany5] = OneToMany(
        DeepOneToMany5, foreign_key="parent_id", on_save="cascade"
    )


class DeepOneToMany3(Model):
    id: str = _id_field()
    parent_id: str | None = None
    children: list[DeepOneToMany4] = OneToMany(
        DeepOneToMany4, foreign_key="parent_id", on_save="cascade"
    )


class DeepOneToMany2(Model):
    id: str = _id_field()
    parent_id: str | None = None
    children: list[DeepOneToMany3] = OneToMany(
        DeepOneToMany3, foreign_key="parent_id", on_save="cascade"
    )


class DeepOneToMany1(Model):
    id: str = _id_field()
    parent_id: str | None = None
    children: list[DeepOneToMany2] = OneToMany(
        DeepOneToMany2, foreign_key="parent_id", on_save="cascade"
    )


class DeepManyToOne7(Model):
    id: str = _id_field()
    value: str = "many-to-one-7"


class DeepManyToOne6(Model):
    id: str = _id_field()
    parent_id: str | None = None
    parent: DeepManyToOne7 = ManyToOne(
        DeepManyToOne7, foreign_key="parent_id", on_save="cascade"
    )


class DeepManyToOne5(Model):
    id: str = _id_field()
    parent_id: str | None = None
    parent: DeepManyToOne6 = ManyToOne(
        DeepManyToOne6, foreign_key="parent_id", on_save="cascade"
    )


class DeepManyToOne4(Model):
    id: str = _id_field()
    parent_id: str | None = None
    parent: DeepManyToOne5 = ManyToOne(
        DeepManyToOne5, foreign_key="parent_id", on_save="cascade"
    )


class DeepManyToOne3(Model):
    id: str = _id_field()
    parent_id: str | None = None
    parent: DeepManyToOne4 = ManyToOne(
        DeepManyToOne4, foreign_key="parent_id", on_save="cascade"
    )


class DeepManyToOne2(Model):
    id: str = _id_field()
    parent_id: str | None = None
    parent: DeepManyToOne3 = ManyToOne(
        DeepManyToOne3, foreign_key="parent_id", on_save="cascade"
    )


class DeepManyToOne1(Model):
    id: str = _id_field()
    parent_id: str | None = None
    parent: DeepManyToOne2 = ManyToOne(
        DeepManyToOne2, foreign_key="parent_id", on_save="cascade"
    )


class DeepManyToMany7(Model):
    id: str = _id_field()
    value: str = "many-to-many-7"


class DeepManyToMany6(Model):
    id: str = _id_field()
    children: list[DeepManyToMany7] = ManyToMany(
        DeepManyToMany7, through="deep_many_to_many_6", on_save="cascade"
    )


class DeepManyToMany5(Model):
    id: str = _id_field()
    children: list[DeepManyToMany6] = ManyToMany(
        DeepManyToMany6, through="deep_many_to_many_5", on_save="cascade"
    )


class DeepManyToMany4(Model):
    id: str = _id_field()
    children: list[DeepManyToMany5] = ManyToMany(
        DeepManyToMany5, through="deep_many_to_many_4", on_save="cascade"
    )


class DeepManyToMany3(Model):
    id: str = _id_field()
    children: list[DeepManyToMany4] = ManyToMany(
        DeepManyToMany4, through="deep_many_to_many_3", on_save="cascade"
    )


class DeepManyToMany2(Model):
    id: str = _id_field()
    children: list[DeepManyToMany3] = ManyToMany(
        DeepManyToMany3, through="deep_many_to_many_2", on_save="cascade"
    )


class DeepManyToMany1(Model):
    id: str = _id_field()
    children: list[DeepManyToMany2] = ManyToMany(
        DeepManyToMany2, through="deep_many_to_many_1", on_save="cascade"
    )


DEEP_RELATION_FAMILIES = {
    "one_to_one": (
        DeepOneToOne1,
        DeepOneToOne2,
        DeepOneToOne3,
        DeepOneToOne4,
        DeepOneToOne5,
        DeepOneToOne6,
        DeepOneToOne7,
    ),
    "one_to_many": (
        DeepOneToMany1,
        DeepOneToMany2,
        DeepOneToMany3,
        DeepOneToMany4,
        DeepOneToMany5,
        DeepOneToMany6,
        DeepOneToMany7,
    ),
    "many_to_one": (
        DeepManyToOne1,
        DeepManyToOne2,
        DeepManyToOne3,
        DeepManyToOne4,
        DeepManyToOne5,
        DeepManyToOne6,
        DeepManyToOne7,
    ),
    "many_to_many": (
        DeepManyToMany1,
        DeepManyToMany2,
        DeepManyToMany3,
        DeepManyToMany4,
        DeepManyToMany5,
        DeepManyToMany6,
        DeepManyToMany7,
    ),
}
