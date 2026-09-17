from __future__ import annotations

from renus.db import DatabaseField, Embedded, EmbeddedMany, Field, Model


class DeepManyLeaf(Model):
    value: str


class DeepMany6(Model):
    children: list[DeepManyLeaf] = EmbeddedMany(DeepManyLeaf)


class DeepMany5(Model):
    children: list[DeepMany6] = EmbeddedMany(DeepMany6)


class DeepMany4(Model):
    children: list[DeepMany5] = EmbeddedMany(DeepMany5)


class DeepMany3(Model):
    children: list[DeepMany4] = EmbeddedMany(DeepMany4)


class DeepMany2(Model):
    children: list[DeepMany3] = EmbeddedMany(DeepMany3)


class DeepMany1(Model):
    children: list[DeepMany2] = EmbeddedMany(DeepMany2)


class DeepEmbedded7(Model):
    value: str


class DeepEmbedded6(Model):
    child: DeepEmbedded7 = Embedded(DeepEmbedded7)


class DeepEmbedded5(Model):
    child: DeepEmbedded6 = Embedded(DeepEmbedded6)


class DeepEmbedded4(Model):
    child: DeepEmbedded5 = Embedded(DeepEmbedded5)


class DeepEmbedded3(Model):
    child: DeepEmbedded4 = Embedded(DeepEmbedded4)


class DeepEmbedded2(Model):
    child: DeepEmbedded3 = Embedded(DeepEmbedded3)


class DeepEmbedded1(Model):
    child: DeepEmbedded2 = Embedded(DeepEmbedded2)


class DeepRoot(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    embedded: DeepEmbedded1 = Embedded(DeepEmbedded1)
    many: list[DeepMany1] = EmbeddedMany(DeepMany1)
