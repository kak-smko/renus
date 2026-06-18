controller_temp='''from renus.core.request import Request
from app.{name}.model import {names_camel}
from renus.core.response import JsonResponse
from renus.core.validation.validate import Validate,vr
from app.extension.codenus.table.model import Table

class {name_camel}Controller:
    def __init__(self,request:Request) -> None:
        self.request=request

    @property
    def __inputs(self):
        return Validate(self.request.inputs).rules({})

    def index(self):
        """
        Get {name_camel} Records
        :method: get
        :return: JsonResponse of CRUD table
        """
        m=Table({names_camel}(self.request))
        m.fields = {
            "_id": {"type": "r-text-input", "formInput": False},
            "updated_at": {"type": "r-time-ago", "formInput": False},
            "created_at": {"type": "r-date-input", "formInput": False, "sortable": False, }
            }
        m.search_fields = []
        return JsonResponse(m.index())

    def store(self):
        """
        Add new {name_camel} Item
        :method: post
        :return: JsonResponse
        """

        {names_camel}(self.request).create(self.__inputs)
        return JsonResponse({"msg": "stored"})

    def update(self, id):
        """
        Update {name_camel} where _id is id
        :method: put
        :param id: {name_camel} _id
        :return: JsonResponse
        """

        {names_camel}(self.request).where({"_id": id}).update(self.__inputs)
        return JsonResponse({"msg": "updated"})

    def delete(self, id):
        """
        Delete {name_camel} where _id is id
        :method: delete
        :param id: {name_camel} _id
        :return: JsonResponse
        """
        {names_camel}(self.request).where({"_id": id}).delete()
        return JsonResponse({"msg": "deleted"})
'''

model_temp='''from datetime import datetime
from bson import ObjectId
from renus.core.model import ModelBase, ReModel
from app.extension.codenus.activity.service import ActivityService

class {name_camel}(ReModel):
    _id: ObjectId
    created_at: datetime
    updated_at: datetime


class {names_camel}(ModelBase[{name_camel}]):
    collection_name="{name_db}"
    document_model={name_camel}

    def __init__(self, request) -> None:
        super().__init__()
        self.request=request

    def boot_event(self, typ: str, old, new, session=None):
        ActivityService().handle(typ, old, new, self.request, self.collection_name, session)
'''

route_temp='''from renus.core.routing import Router
from renus.core.config import Config
from app.{name}.controller import {name_camel}Controller
from app.extension.codenus.permission.middleware import PermissionMiddleware
from app.extension.codenus.user.middleware import AuthMiddleware

r=Router(subdomain=Config("app").get("admin_subdomain","admin"),
         prefix="api/admin{folder}", middlewares=[AuthMiddleware, PermissionMiddleware("admin")])
r.crud("/{names}",{name_camel}Controller, middlewares=[PermissionMiddleware("{names}")])

u=Router(prefix="api/user", middlewares=[AuthMiddleware])

h=Router(prefix="api/home")
'''

vue_temp='''<template>
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