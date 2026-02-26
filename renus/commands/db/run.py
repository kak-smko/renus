import base64
import datetime
import json
import os
import shutil
import uuid

from bson import (ObjectId, Decimal128, Binary, Regex, Code, Timestamp, DBRef, Int64, MinKey, MaxKey)

from renus.core.model import ModelBase


class MongoJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return {"$oid": str(obj)}
        elif isinstance(obj, datetime.datetime):
            return {"$date": obj.isoformat() + 'Z' if obj.tzinfo is None else obj.isoformat()}
        elif isinstance(obj, Decimal128):
            return {"$numberDecimal": str(obj)}
        elif isinstance(obj, Binary):
            return {
                "$binary": {
                    "base64": base64.b64encode(obj).decode('utf-8'),
                    "subType": obj.subtype
                }
            }
        elif isinstance(obj, Regex):
            return {
                "$regularExpression": {
                    "pattern": obj.pattern,
                    "options": obj.flags
                }
            }
        elif isinstance(obj, Code):
            if obj.scope:
                return {"$code": str(obj), "$scope": obj.scope}
            return {"$code": str(obj)}
        elif isinstance(obj, Timestamp):
            return {
                "$timestamp": {
                    "t": obj.time,
                    "i": obj.inc
                }
            }
        elif isinstance(obj, Int64):
            return {"$numberLong": str(obj)}
        elif isinstance(obj, (int, float)):
            if isinstance(obj, bool):
                return obj
            elif obj > 2 ** 31 - 1 or obj < -2 ** 31:
                return {"$numberLong": str(int(obj))}
            return obj
        elif isinstance(obj, MinKey):
            return {"$minKey": 1}
        elif isinstance(obj, MaxKey):
            return {"$maxKey": 1}
        elif isinstance(obj, uuid.UUID):
            return {"$uuid": str(obj)}
        elif isinstance(obj, DBRef):
            return {
                "$ref": obj.collection,
                "$id": self.default(obj.id),
                "$db": obj.database  # Only included if present
            }
        elif isinstance(obj, bytes):
            # Handle raw bytes (not Binary)
            return {
                "$binary": {
                    "base64": base64.b64encode(obj).decode('utf-8'),
                    "subType": "00"
                }
            }
        elif hasattr(obj, 'items'):
            return {k: self.default(v) for k, v in obj.items()}
        elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
            return [self.default(v) for v in obj]

        return super().default(obj)


def mongo_json_decoder(obj):
    if not isinstance(obj, dict):
        return obj

    if "$oid" in obj:
        return ObjectId(obj["$oid"])
    elif "$date" in obj:
        try:
            # Handle both string and milliseconds formats
            if isinstance(obj["$date"], str):
                return datetime.datetime.fromisoformat(obj["$date"].rstrip('Z'))
            else:
                return datetime.datetime.fromtimestamp(obj["$date"] / 1000.0)
        except (ValueError, TypeError):
            return obj["$date"]
    elif "$numberDecimal" in obj:
        return Decimal128(obj["$numberDecimal"])
    elif "$binary" in obj:
        base64_str = obj["$binary"]["base64"]
        subtype = obj["$binary"].get("subType", 0)
        return Binary(base64.b64decode(base64_str), subtype)
    elif "$regularExpression" in obj:
        pattern = obj["$regularExpression"]["pattern"]
        options = obj["$regularExpression"].get("options", "")
        return Regex(pattern, options)
    elif "$code" in obj:
        if "$scope" in obj:
            return Code(obj["$code"], scope=obj["$scope"])
        return Code(obj["$code"])
    elif "$timestamp" in obj:
        return Timestamp(obj["$timestamp"]["t"], obj["$timestamp"]["i"])
    elif "$numberLong" in obj:
        return Int64(obj["$numberLong"])
    elif "$numberInt" in obj:
        return int(obj["$numberInt"])
    elif "$numberDouble" in obj:
        return float(obj["$numberDouble"])
    elif "$minKey" in obj:
        return MinKey()
    elif "$maxKey" in obj:
        return MaxKey()
    elif "$uuid" in obj:
        return uuid.UUID(obj["$uuid"])
    elif "$undefined" in obj:
        return None
    elif "$symbol" in obj:
        return obj["$symbol"]
    elif "$dbPointer" in obj:
        return DBRef(obj["$dbPointer"]["$ref"], obj["$dbPointer"]["$id"])
    elif "$ref" in obj and "$id" in obj:  # DBRef without $dbPointer wrapper
        return DBRef(obj["$ref"], obj["$id"])

    # Handle nested objects recursively
    for key, value in obj.items():
        if isinstance(value, dict):
            obj[key] = mongo_json_decoder(value)
        elif isinstance(value, list):
            obj[key] = [mongo_json_decoder(item) for item in value]

    return obj


def drop():
    collections = ModelBase().db.list_collection_names()
    for collection in collections:
        print('drop', collection)
        ModelBase().db.drop_collection(collection)

def backup():
    collections = ModelBase().db.list_collection_names()
    for collection in collections:
        print('backup', collection)
        data = ModelBase().set_collection(collection).get()
        json.dump(data, open(f"./db/{collection}", "w"), cls=MongoJSONEncoder)


def restore():
    with os.scandir('./db') as entries:
        for entry in entries:
            if entry.is_file():
                ModelBase().db.drop_collection(entry.name)
                data = json.load(open(entry.path, 'r'), object_hook=mongo_json_decoder)
                ModelBase().collection(entry.name).insert_many(data)
                print('restore', entry.name)


def run(args=None):
    if args and '--drop' in args:
        print(f'start dropping')
        drop()

    elif args and '--backup' in args:
        print(f'start backing up in ./db')
        shutil.rmtree("./db", ignore_errors=True)
        os.mkdir("./db")
        backup()

    elif args and '--restore' in args:
        print(f'start restore db from ./db')
        restore()

    print('end')
