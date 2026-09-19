from __future__ import annotations

from renus.db import DatabaseField, Embedded, EmbeddedMany, Field, Model


class DeepMany7(Model):
    name:str


class DeepMany6(Model):
    name:str
    children: list[DeepMany7] = EmbeddedMany(DeepMany7)


class DeepMany5(Model):
    name:str
    children: list[DeepMany6] = EmbeddedMany(DeepMany6)


class DeepMany4(Model):
    name:str
    children: list[DeepMany5] = EmbeddedMany(DeepMany5)


class DeepMany3(Model):
    name:str
    children: list[DeepMany4] = EmbeddedMany(DeepMany4)


class DeepMany2(Model):
    name:str
    children: list[DeepMany3] = EmbeddedMany(DeepMany3)


class DeepMany1(Model):
    name:str
    children: list[DeepMany2] = EmbeddedMany(DeepMany2)


class DeepEmbedded7(Model):
    name:str
    value: str


class DeepEmbedded6(Model):
    name:str
    child: DeepEmbedded7 = Embedded(DeepEmbedded7)


class DeepEmbedded5(Model):
    name:str
    child: DeepEmbedded6 = Embedded(DeepEmbedded6)


class DeepEmbedded4(Model):
    name:str
    child: DeepEmbedded5 = Embedded(DeepEmbedded5)


class DeepEmbedded3(Model):
    name:str
    child: DeepEmbedded4 = Embedded(DeepEmbedded4)


class DeepEmbedded2(Model):
    name:str
    child: DeepEmbedded3 = Embedded(DeepEmbedded3)


class DeepEmbedded1(Model):
    name:str
    child: DeepEmbedded2 = Embedded(DeepEmbedded2)


class DeepRoot(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name:str
    embedded: DeepEmbedded1 = Embedded(DeepEmbedded1)
    many: list[DeepMany1] = EmbeddedMany(DeepMany1)
