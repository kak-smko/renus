from __future__ import annotations

from renus.db import DatabaseField, Field, Model


class DeepMany7(Model):
    name:str


class DeepMany6(Model):
    name:str
    children: list[DeepMany7] = Field(default_factory=list)


class DeepMany5(Model):
    name:str
    children: list[DeepMany6] = Field(default_factory=list)


class DeepMany4(Model):
    name:str
    children: list[DeepMany5] = Field(default_factory=list)


class DeepMany3(Model):
    name:str
    children: list[DeepMany4] = Field(default_factory=list)


class DeepMany2(Model):
    name:str
    children: list[DeepMany3] = Field(default_factory=list)


class DeepMany1(Model):
    name:str
    children: list[DeepMany2] = Field(default_factory=list)


class DeepEmbedded7(Model):
    name:str
    value: str


class DeepEmbedded6(Model):
    name:str
    child: DeepEmbedded7 | None = None


class DeepEmbedded5(Model):
    name:str
    child: DeepEmbedded6 | None = None


class DeepEmbedded4(Model):
    name:str
    child: DeepEmbedded5 | None = None


class DeepEmbedded3(Model):
    name:str
    child: DeepEmbedded4 | None = None


class DeepEmbedded2(Model):
    name:str
    child: DeepEmbedded3 | None = None


class DeepEmbedded1(Model):
    name:str
    child: DeepEmbedded2 | None = None


class DeepRoot(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name:str
    embedded: DeepEmbedded1 | None = None
    many: list[DeepMany1] = Field(default_factory=list)
