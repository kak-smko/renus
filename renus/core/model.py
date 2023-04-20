import os
import typing

from bson import ObjectId
from pymongo import MongoClient
from datetime import datetime
from renus.core.config import Config
from renus.util.helper import dictAttribute

class ModelBase:
    _client = MongoClient(Config('database').get('host', '127.0.0.1'),
                          Config('database').get('port', 27017),
                          username=Config('database').get('username', None),
                          password=Config('database').get('password', None))

    _database_name = Config('database').get('name', 'renus')
    _collection_name=None
    metro = None
    _public_folder='public'
    hidden_fields = []
    fields = {}
    _base_model=dictAttribute
    def __init__(self) -> None:
        self._steps = None
        self._where = None
        self._distinct = None
        self._limit = None
        self._skip = None
        self._sort = None
        self._select = None
        self.visible_fields = []

    def __iter__(self):
        return iter(self.get())

    def set_database(self, name: str):
        self._database_name = name
        return self

    def set_collection(self, name: str):
        self._collection_name = name
        return self

    @property
    def db(self):
        return self._client[self._database_name]

    def collection(self, name: str = None):
        if name is None:
            name = self._collection_name

        return self.db[name]

    def reset(self):
        self._steps = None
        self._where = None
        self._distinct = None
        self._limit = None
        self._skip = None
        self._sort = None
        self._select = None
        self.visible_fields = []
        return self

    def create_index(self, fields, unique=False):
        return self.collection().create_index(fields,
                                              unique=unique)

    def aggregate(self, pipeline: typing.Any, session: typing.Any = None):
        return self.__police(self.collection().aggregate(pipeline, session))

    def where(self, where: dict):
        if self._steps is not None:
            self._steps.append({
                "$match": where
            })
        else:
            if self._where is None:
                self._where = {}
            for k,v in where.items():
                if k.startswith('$') and k in self._where:
                    if type(v) is list:
                        self._where[k]+=v
                    else:
                        self._where[k]={**self._where[k],**v}
                else:
                    self._where[k] = v

        return self

    def count(self, skip=False, limit=False):
        k = {}
        if self._where is not None:
            k['filter'] = self._where
        else :
            k['filter'] = {}
        if skip and self._skip is not None:
            k['skip'] = self._skip
        if limit and self._limit is not None:
            k['limit'] = self._limit
        
        return self.collection().count_documents(**k)

    def distinct(self, key: str):
        self._distinct = key
        return self

    def limit(self, count: int):
        if self._steps is not None:
            self._steps.append({"$limit": count})
        else:
            self._limit = count
        return self

    def skip(self, count: int):
        if self._steps is not None:
            self._steps.append({"$skip": count})
        else:
            self._skip = count
        return self

    def group(self, item: dict):
        if self._steps is None:
            raise RuntimeError("group work with steps() architect")
        self._steps.append({"$group": item})
        return self

    def sort(self, key_or_list: typing.Union[str, typing.List[typing.Tuple]], asc: bool = True):
        if type(key_or_list) is dict:
            s = key_or_list
        elif type(key_or_list) is list:
            s = []
            for f, a in key_or_list:
                s.append((f, 1 if a else -1))
        else:
            s = [(key_or_list, 1 if asc else -1)]
        if self._steps is not None:
            if type(s) is list:
                s = {i[0]: i[1] for i in s}
            self._steps.append({"$sort": s})
        else:
            self._sort=s
        return self

    def select(self, *select: [str, typing.Dict]):
        s = {}
        if len(select)==1 and type(select[0]) is dict:
            s=select[0]
        else:
            for key in select:
                if type(key) is dict:
                    s = key
                else:
                    s[key] = 1

        if self._steps is not None:
            self._steps.append({'$project': s})
            return self

        self._select=s
        return self

    def with_relation(self, collection, local_field, forigen_field, to,single=False):
        if self._steps is not None:
            self._steps.append({
                "$lookup": {
                    "from": collection,
                    "localField": local_field,
                    "foreignField": forigen_field,
                    "as": to
                }
            })
            if single:
                self._steps.append({'$unwind': f'${to}'})
        return self

    def steps(self):
        self._steps = []
        return self

    def _get(self, police: bool = True) -> typing.List[_base_model]:
        if self._steps is not None:
            return self.aggregate(self._steps)

        where, select = self._base_gate(police)

        find = self.collection().find(where, select)

        if self._sort is not None:
            find = find.sort(self._sort)
        if self._skip is not None:
            find = find.skip(self._skip)
        if self._limit is not None:
            find = find.limit(self._limit)
        if self._distinct is not None:
            return find.distinct(self._distinct)

        return self.__police(find) if police else list(find)

    def get(self,police: bool = True) -> typing.List[_base_model]:
        return self._get(police)

    def _first(self, police: bool = True) -> typing.Union[_base_model,None]:
        self.limit(1)
        res = self.get(police)
        self._limit = None
        if len(res) == 1:
            return res[0]
        return None

    def first(self, police: bool = True) -> typing.Union[_base_model, None]:
        return self._first(police)

    def create(self, document: dict) -> dict:
        if "updated_at" not in document:
            document["updated_at"] = datetime.utcnow()

        if "created_at" not in document:
            document["created_at"] = datetime.utcnow()

        id = self.collection().insert_one(document).inserted_id
        document['_id'] = id
        self.boot_event('create', {}, document)
        return document

    def create_many(self, documents: typing.List) -> typing.List[ObjectId]:
        for document in documents:
            if "updated_at" not in document:
                document["updated_at"] = datetime.utcnow()

            if "created_at" not in document:
                document["created_at"] = datetime.utcnow()

        ids = self.collection().insert_many(documents).inserted_ids
        self.boot_event('create_many', {}, ids)
        return ids

    def update(self, new: dict, upsert=False, get_old=False) -> bool:
        where = self.__ud_gate('update')
        new["updated_at"] = datetime.utcnow()
        d = {"$set": new}
        if "created_at" not in new:
            d["$setOnInsert"] = {'created_at': datetime.utcnow()}
        old = self.collection().find_one_and_update(where, d, upsert=upsert)
        self.boot_event('update', old, new)
        return old if get_old else True

    def update_opt(self, new: dict, upsert=False, get_old=False) -> bool:
        where = self.__ud_gate('update')
        if '$set' not in new:
            new['$set'] = {}
        if '$setOnInsert' not in new:
            new['$setOnInsert'] = {}
        new['$set']["updated_at"] = datetime.utcnow()
        new['$setOnInsert']['created_at'] = datetime.utcnow()
        old = self.collection().find_one_and_update(where, new, upsert=upsert)
        self.boot_event('update', old, {k[1:]:v for k,v in new.items()})
        return old if get_old else True

    def update_opt_many(self, new: dict, upsert=False, get_old=False) -> bool:
        where = self.__ud_gate('update')
        if '$set' not in new:
            new['$set'] = {}
        if '$setOnInsert' not in new:
            new['$setOnInsert'] = {}
        new['$set']["updated_at"] = datetime.utcnow()
        new['$setOnInsert']['created_at'] = datetime.utcnow()
        old = self.collection().update_many(where, new, upsert=upsert).raw_result
        self.boot_event('update', old, {k[1:]:v for k,v in new.items()})
        return old if get_old else True

    def update_many(self, new: dict) -> bool:
        where = self.__ud_gate('update')
        new["updated_at"] = datetime.utcnow()
        old = self.collection().update_many(where, {"$set": new}).raw_result
        self.boot_event('update_many', old, str(new))
        return True

    def delete(self, all: bool = False) -> bool:
        where = self.__ud_gate('delete')
        if all is False:
            old = self.collection().find_one_and_delete(where)
            if self.metro is not None:
                self._handle_metro('delete', old)
            self.boot_event('delete', old, {})
        else:
            if self.metro is not None:
                self._handle_metro('delete')
            old = self.collection().delete_many(where)

            self.boot_event('delete_many', {'deleted_count': old.deleted_count, 'where': str(where)}, {})

        return old

    def make_visible(self, fields: typing.List):
        self.visible_fields=fields
        return self

    @staticmethod
    def boot_event(typ: str, old, new):
        pass

    @staticmethod
    def convert_id(id):
        if type(id) is str:
            try:
                return ObjectId(id)
            except Exception:
                return id
        return id

    def _base_gate(self, police) -> list:
        where = self._where
        select = self._select

        if select is None and police == False:
            raise RuntimeError("when police is off, for security reason select fields. ex: .select('_id','name')")

        if where is not None:
            if '_id' in where:
                where['_id'] = self.convert_id(where['_id'])

        return [where, select]

    @staticmethod
    def cast(document:dict):
        return document

    def __cleaner(self, document: dict):
        for field in self.hidden_fields:
            if field in document and field not in self.visible_fields:
                del document[field]

        return self._base_model(self.cast(document))

    def __police(self, documents: typing.Any):
        if documents is None:
            return None
        res = []
        if type(documents) is dict:
            return self.__cleaner(documents)
        else:
            for document in documents:
                if type(document) is dict:
                    res.append(self.__cleaner(document))
        return res

    def __ud_gate(self, type: str):
        where = self._where
        if where is None:
            raise RuntimeError(f"for {type} use where. ex: .where({'name':'test'})")
        if '_id' in where:
            where['_id'] = self.convert_id(where['_id'])

        return where

    def _handle_metro(self, typ, obj=None):
        if typ == 'delete':
            if obj is None:
                where = self.__ud_gate('delete')
                all = self.collection().find(where)
            else:
                all = [obj]

            for item in all:
                for field, db in self.metro.items():
                    if type(db) is not list:
                        raise RuntimeError("metro format not true. ex: '_id':[{'collection':'test','field': 'test_id'}]")
                    for d in db:
                        strg=d.get('storage',False)
                        c=d.get('collection',False)
                        if c is not False:
                            if strg:
                                files = self.collection(c).find({
                                    d['field']: item[field]
                                })

                                for file in files:
                                    self._remove_file(file.get(strg, []))
                            self.collection(c).delete_many({
                                d['field']: item[field]
                            })
                        elif strg is not False:
                            l = self.__get_links(strg, item)
                            if l:
                                self._remove_file(l)


    def __get_links(self,field:str,doc:dict):
        item = doc.copy()
        p = field.split('.')
        r = None
        for i in p:
            if i not in item:
                return False
            r = item[i]
            item = item[i]
        return r

    def _remove_file(self, links):
        if type(links) is dict:
            links = list(links.values())
        if type(links) is not list:
            links = [links]

        for link in links:
            if type(link) is str:
                link = link.replace('storage/img/', '', 1)
                link = link.replace('storage/', '', 1)
            elif type(link) is dict:
                link = link.get('url').replace('storage/img/', '', 1)
                link = link.replace('storage/', '', 1)
            else:
                raise RuntimeError(f"type {link} must be string or dict but its {type(link)}")

            try:
                os.remove(f'storage/{self._public_folder}/' + link)
            except:
                pass

    @property
    def database_name(self):
        return self._database_name
