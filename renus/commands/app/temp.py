controller_temp = '''from renus.request import Request
from renus.response import JsonResponse
from app.{name}.model import {name_camel}

class {name_camel}Controller:
    def __init__(self, request: Request) -> None:
        self.request = request

    @property
    def repo(self):
        """Repository bound to the request-scoped database.

        ``db`` is placed on ``app.state`` at startup and exposed on each
        request, so controllers reach it generically via ``self.request.db``.
        """
        db = self.request.db
        return db.repository({name_camel})

    @property
    def __inputs(self):
        return {name_camel}(self.request.inputs).to_dict()

    async def index(self):
        """Get {name_camel} Records.
        :method: get
        :return: JsonResponse
        """
        records = await self.repo.query().all()
        return JsonResponse([dict(r) for r in records])

    async def store(self):
        """Add new {name_camel} Item.
        :method: post
        :return: JsonResponse
        """
        await self.repo.create({name_camel}(**self.__inputs))
        return JsonResponse({"msg": "stored"})

    async def update(self, id):
        """Update {name_camel} by primary key.
        :method: put
        :param id: {name_camel} primary key
        :return: JsonResponse
        """
        values = {k: v for k, v in self.__inputs.items() if k != "id"}
        await self.repo.update({name_camel}.id == id, values=values)
        return JsonResponse({"msg": "updated"})

    async def delete(self, id):
        """Delete {name_camel} by primary key.
        :method: delete
        :param id: {name_camel} primary key
        :return: JsonResponse
        """
        await self.repo.delete({name_camel}.id == id)
        return JsonResponse({"msg": "deleted"})
'''

model_temp = '''from __future__ import annotations

from renus.db import DatabaseField, Field, Model

class {name_camel}(Model):
    """Domain model for {name}.

    Field rules run during :meth:`validate` and on instantiation; metadata is
    inferred for schema creation (``db.create_schema``). A natural string
    primary key keeps the model portable across SQL and MongoDB backends.
    """

    id: str = Field(database=DatabaseField(primary_key=True))

    # --- Example fields; customize for your domain. ---
    name: str = Field(max_len=120)
    payload: dict | None = None

    class Meta:
        soft_delete = True
        timestamps = True
'''

route_temp = '''from renus.router import Router
from renus.config import Config
from app.{name}.controller import {name_camel}Controller

r = Router(
    subdomain=Config("app").get("admin_subdomain", "admin"),
    prefix="api/admin{folder}",
)
r.crud("/{names}", {name_camel}Controller)

h = Router(prefix="api/home")
'''

route_user_temp = '''from renus.router import Router
from renus.config import Config
from app.{name}.controller import {name_camel}Controller
from app.extension.codenus.user.middleware import AuthMiddleware
from app.extension.codenus.user.middleware import PermissionMiddleware

r = Router(
    subdomain=Config("app").get("admin_subdomain", "admin"),
    prefix="api/admin{folder}",
    middlewares=[AuthMiddleware, PermissionMiddleware("admin")],
)
r.crud("/{names}", {name_camel}Controller, middlewares=[PermissionMiddleware("{names}")])

u = Router(prefix="api/user", middlewares=[AuthMiddleware])
h = Router(prefix="api/home")
'''

vue_temp = '''<template>
  <r-container class="container-fluid">
    <r-table-crud link="admin/{folder}{names}"></r-table-crud>
  </r-container>
</template>

<script>
export default {
  name: "{name}"
};
</script>
'''
