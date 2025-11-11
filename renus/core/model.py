from datetime import datetime
from typing import TypeVar, Generic, Any, List, Optional, Union, Tuple, Dict, get_origin, get_args

from bson import ObjectId
from pymongo import MongoClient

from renus.core.config import Config
from renus.core.cprint import Cprint


class ReModel:
    def __init__(self, doc):
        self._convert_dict_to_objects(doc)

    def _convert_dict_to_objects(self, doc):
        annotations = getattr(self.__class__, '__annotations__', {})

        for k, v in doc.items():
            field_type = annotations.get(k)

            if isinstance(v, dict):
                if field_type and isinstance(field_type, type) and issubclass(field_type, ReModel):
                    v = field_type(v)

            elif isinstance(v, list):
                v = self._process_list_items(v, field_type)

            setattr(self, k, v)

    def _process_list_items(self, items, field_type):
        if not field_type:
            return items

        origin = get_origin(field_type)
        if origin is list and items:
            args = get_args(field_type)
            if args and issubclass(args[0], ReModel):
                r = []
                for item in items:
                    if isinstance(item, dict):
                        r.append(args[0](item))
                    else:
                        r.append(item)
                return r

        return items

    def __iter__(self):
        return iter(self.__dict__.items())

    def __getitem__(self, item):
        return self.__dict__[item]

    def __repr__(self):
        return f"{self.__class__.__name__}({self.__dict__})"


M = TypeVar('T')


class ModelBase(Generic[M]):
    client = MongoClient(Config('database').get('host', '127.0.0.1'),
                         Config('database').get('port', 27017),
                         username=Config('database').get('username', None),
                         password=Config('database').get('password', None))

    _database_name = Config('database').get('name', 'renus')
    collection_name = None
    metro = None
    storage = None
    hidden_fields = []
    document_model = dict
    add_time_fields = True

    def __init__(self) -> None:
        if hasattr(self, '_collection_name'):
            raise RuntimeError('_collection_name has expired. Use collection_name')

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
        self.collection_name = name
        return self

    @property
    def db(self):
        return self.client[self._database_name]

    def collection(self, name: str = None):
        if name is None:
            name = self.collection_name

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

    def aggregate(self, pipeline: Any, session: Any = None):
        return self.__police(self.collection().aggregate(pipeline, session))

    def where(self, where: dict):
        if self._steps is not None:
            self._steps.append({
                "$match": where
            })
        else:
            if self._where is None:
                self._where = {}
            for k, v in where.items():
                if k.startswith('$') and k in self._where:
                    if type(v) is list:
                        self._where[k] += v
                    else:
                        self._where[k] = {**self._where[k], **v}
                else:
                    self._where[k] = v

        return self

    def count(self, skip=False, limit=False):
        k = {}
        if self._where is not None:
            k['filter'] = self._where
        else:
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

    def sort(self, key_or_list: Union[str, List[Tuple]], asc: bool = True):
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
            self._sort = s
        return self

    def select(self, *select: [str, Dict]):
        s = {}
        if len(select) == 1 and type(select[0]) is dict:
            s = select[0]
        else:
            for key in select:
                if type(key) is dict:
                    s = key
                else:
                    s[key] = 1

        if self._steps is not None:
            self._steps.append({'$project': s})
            return self

        self._select = s
        return self

    def with_relation(self, collection, local_field, forigen_field, to, single=False, pipeline=None):
        if pipeline is None:
            pipeline = []
        if self._steps is not None:
            self._steps.append({
                "$lookup": {
                    "from": collection,
                    "localField": local_field,
                    "foreignField": forigen_field,
                    "as": to,
                    "pipeline": pipeline
                }
            })
            if single:
                self._steps.append({'$addFields': {f'{to}': {'$arrayElemAt': [f"${to}", 0]}}})
        else:
            c = Cprint()
            c.print(c.red('use steps mode for with_relation.'))
        return self

    def steps(self):
        self._steps = []
        return self

    def get(self, police: bool = True, session=None) -> List[M]:
        if self._steps is not None:
            return self.aggregate(self._steps, session)

        where, select = self._base_gate(police)

        find = self.collection().find(where, select, session=session)

        if self._sort is not None:
            find = find.sort(self._sort)
        if self._skip is not None:
            find = find.skip(self._skip)
        if self._limit is not None:
            find = find.limit(self._limit)
        if self._distinct is not None:
            return find.distinct(self._distinct)

        return self.__police(find) if police else list(find)

    def first(self, police: bool = True, session=None) -> Optional[M]:
        self.limit(1)
        res = self.get(police, session)
        self._limit = None
        if len(res) == 1:
            return res[0]
        return None

    def create(self, document: dict, session=None) -> dict:
        if self.add_time_fields and "updated_at" not in document:
            document["updated_at"] = datetime.utcnow()

        if self.add_time_fields and "created_at" not in document:
            document["created_at"] = datetime.utcnow()

        id = self.collection().insert_one(document, session=session).inserted_id
        document['_id'] = id
        self.boot_event('create', {}, document, session)
        self._attach_file(document, session)
        return document

    def create_many(self, documents: List, session=None) -> List[ObjectId]:
        if self.add_time_fields:
            for document in documents:
                if "updated_at" not in document:
                    document["updated_at"] = datetime.utcnow()

                if "created_at" not in document:
                    document["created_at"] = datetime.utcnow()

        ids = self.collection().insert_many(documents, session=session).inserted_ids
        self.boot_event('create_many', {}, ids, session)
        self._attach_file({'_id': 'create_many', 'documents': documents}, session)
        return ids

    def update(self, new: dict, upsert=False, get_old=False, session=None) -> bool:
        where = self.__ud_gate('update')
        if self.add_time_fields:
            new["updated_at"] = datetime.utcnow()
        d = {"$set": new}
        if self.add_time_fields and "created_at" not in new:
            d["$setOnInsert"] = {'created_at': datetime.utcnow()}
        old = self.collection().find_one_and_update(where, d, upsert=upsert, session=session)
        self.boot_event('update', old, new, session)
        if old is None:
            new = {'_id': 'upsert', 'doc': new}
        else:
            new['_id'] = old['_id']
        self._attach_file(new, session)
        return old if get_old else True

    def update_opt(self, new: dict, upsert=False, get_old=False, session=None) -> bool:
        where = self.__ud_gate('update')
        if '$set' not in new:
            new['$set'] = {}
        if '$setOnInsert' not in new:
            new['$setOnInsert'] = {}
        if self.add_time_fields:
            new['$set']["updated_at"] = datetime.utcnow()
            new['$setOnInsert']['created_at'] = datetime.utcnow()
        old = self.collection().find_one_and_update(where, new, upsert=upsert, session=session)
        self.boot_event('update', old, {k[1:]: v for k, v in new.items()}, session)
        if old is None:
            new = {'_id': 'upsert', 'doc': new}
        else:
            new['_id'] = old['_id']
        self._attach_file(new, session)
        return old if get_old else True

    def update_opt_many(self, new: dict, upsert=False, get_old=False, session=None) -> bool:
        where = self.__ud_gate('update')
        if '$set' not in new:
            new['$set'] = {}
        if '$setOnInsert' not in new:
            new['$setOnInsert'] = {}
        if self.add_time_fields:
            new['$set']["updated_at"] = datetime.utcnow()
            new['$setOnInsert']['created_at'] = datetime.utcnow()
        old = self.collection().update_many(where, new, upsert=upsert, session=session).raw_result
        self.boot_event('update_many', old, {k[1:]: v for k, v in new.items()}, session)
        self._attach_file({'_id': 'update_opt_many', 'documents': new}, session)
        return old if get_old else True

    def update_many(self, new: dict, session=None) -> bool:
        where = self.__ud_gate('update')
        if self.add_time_fields:
            new["updated_at"] = datetime.utcnow()
        old = self.collection().update_many(where, {"$set": new}, session=session).raw_result
        self.boot_event('update_many', old, str(new), session)
        self._attach_file({'_id': 'update_many', 'documents': new}, session)
        return True

    def delete(self, all: bool = False, session=None) -> bool:
        where = self.__ud_gate('delete')
        if all is False:
            old = self.collection().find_one_and_delete(where, session=session)
            if self.metro is not None:
                self._handle_metro('delete', old, session=session)
            self.boot_event('delete', old, {}, session)
        else:
            if self.metro is not None:
                self._handle_metro('delete', session=session)
            old = self.collection().delete_many(where, session=session)

            self.boot_event('delete_many', {'deleted_count': old.deleted_count, 'where': str(where)}, {}, session)

        return old

    def make_visible(self, fields: List):
        self.visible_fields = fields
        return self

    @staticmethod
    def boot_event(typ: str, old, new, session):
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
    def cast(document: dict):
        return document

    def __cleaner(self, document: dict):
        for field in self.hidden_fields:
            if field in document and field not in self.visible_fields:
                del document[field]

        return self.document_model(self.cast(document))

    def __police(self, documents: Any):
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

    def _handle_metro(self, typ, obj=None, session=None):
        if typ == 'delete':
            if obj is None:
                where = self.__ud_gate('delete')
                all = self.collection().find(where, session=session)
            else:
                all = [obj]

            for item in all:
                for field, db in self.metro.items():
                    if type(db) is not list:
                        raise RuntimeError(
                            "metro format not true. ex: '_id':[{'collection':'test','field': 'test_id'}]")
                    for d in db:
                        c = d.get('collection', False)
                        if c is not False:
                            if self.storage:
                                ids = list(self.collection(c).find({
                                    d['field']: item[field]
                                }, {"_id": 1}, session=session))
                                for id_item in ids:
                                    self._detach_file(id_item, session)
                            self.collection(c).delete_many({
                                d['field']: item[field]
                            }, session=session)

                self._detach_file(item, session)

    def __get_links(self, field: str, doc: dict):
        item = doc.copy()
        p = field.split('.')
        r = None
        for i in p:
            if type(item) is list:
                res = []
                for f in item:
                    if i not in f:
                        return False
                    res.append(f[i])
                return res
            else:
                if i not in item:
                    return False
                r = item[i]
                item = item[i]
        return r

    def _attach_file(self, item, session):
        if self.storage is None or self.metro is None:
            return
        links = self._links_extractor(item)
        self.storage.reset().where({
            'path': {'$in': links}
        }).update_many({'type': self.collection_name, 'type_id': item['_id']}, session=session)

    def _detach_file(self, item, session):
        if self.storage is None or self.metro is None:
            return
        self.storage.reset().where({
            'type_id': item['_id']
        }).update_many({'type': None, 'type_id': None}, session=session)


    @property
    def database_name(self):
        return self._database_name

    def _links_extractor(self, item) -> list:
        s = []
        for field, db in self.metro.items():
            if type(db) is not list:
                raise RuntimeError(
                    "metro format not true. ex: '_id':[{'collection':'test','field': 'test_id'}]")
            for d in db:
                strg = d.get('storage', False)
                if strg is not False:
                    l = self.__get_links(strg, item)
                    if l:
                        s.extend(l)

        return s
