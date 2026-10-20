controller_temp = '''from renus.request import Request
from renus.response import JsonResponse,Status
from app.extension.codenus.kit.table.service import Table
from renus.db import Repository
from renus.db.validation import Validate
from renus.datastructures import ID
from app.{name}.model import {name_camel}

class {name_camel}Controller:
    def __init__(self, request: Request) -> None:
        self.request = request
        self.repo:Repository[{name_camel}] = request.db.repository({name_camel})

    async def index(self):
        table = Table({name_camel}, self.request)
        table.search_fields = []
        return JsonResponse(await table.index())

    async def store(self):
        payload = await self.request.form()
        payload = {name_camel}(dict(payload))

        await self.repo.create(payload)
        return JsonResponse({"msg": "stored"}, Status.HTTP_201_CREATED)

    async def update(self, id: ID):
        payload = await self.request.form()
        payload = Validate({name_camel},payload,None)

        await self.repo.where({name_camel}.id == id).update(payload)
        return JsonResponse({"msg": "updated"})

    async def delete(self, id: ID):
        await self.repo.delete({name_camel}.id == id)
        return JsonResponse({"msg": "deleted"})
{soft_delete_controller}
'''

model_temp = '''from __future__ import annotations

from renus.db import DatabaseField, Field, Model
from renus.db.validation import MaxLen
from renus.datastructures import ID

class {name_camel}(Model):
    """Domain model for {name}.
    """

    id: ID = Field(default_factory=ID,database=DatabaseField(primary_key=True,generated=True))

    # --- Example fields; customize for your domain. ---
    name: str = Field(MaxLen(120))

    class Meta:
        timestamps = True
{soft_delete_meta}
'''

route_temp = '''from renus.router import Router
from renus.config import Config
from app.{name}.controller import {name_camel}Controller

admin_router = Router(
    subdomain=Config("app").get("admin_subdomain", "admin"),
    prefix="/admin{folder}",
)
admin_router.get("/{names}", {name_camel}Controller, "index")
admin_router.post("/{names}", {name_camel}Controller, "store")
admin_router.put("/{names}/{id:id}", {name_camel}Controller, "update")
admin_router.delete("/{names}/{id:id}", {name_camel}Controller, "delete")
{soft_delete_routes}


router = Router()
router.include(admin_router)
'''

route_kit_temp = '''from renus.router import Router
from renus.config import Config
from app.{name}.controller import {name_camel}Controller
from app.extension.codenus.kit.middlewares.auth import AuthMiddleware
from app.extension.codenus.kit.middlewares.permission import PermissionMiddleware

admin_router = Router(
    subdomain=Config("app").get("admin_subdomain", "admin"),
    prefix="/admin{folder}",
    middlewares=[AuthMiddleware, PermissionMiddleware("admin")],
)
admin_router.get("/{names}", {name_camel}Controller, "index", middlewares=[PermissionMiddleware("{names}.view")])
admin_router.post("/{names}", {name_camel}Controller, "store", middlewares=[PermissionMiddleware("{names}.create")])
admin_router.put("/{names}/{id:id}", {name_camel}Controller, "update", middlewares=[PermissionMiddleware("{names}.edit")])
admin_router.delete("/{names}/{id:id}", {name_camel}Controller, "delete", middlewares=[PermissionMiddleware("{names}.delete")])
{soft_delete_kit_routes}

user_router = Router(prefix="/user", middlewares=[AuthMiddleware])
home_router = Router(prefix="/home")
router = Router()
router.include(admin_router)
router.include(user_router)
router.include(home_router)
'''

vue_temp = '''<template>
  <r-container class="container-fluid">
    <r-table-crud link="admin/{folder}{names}"{soft_delete_attribute}></r-table-crud>
  </r-container>
</template>

<script>
export default {
  name: "{name}"
};
</script>
'''
