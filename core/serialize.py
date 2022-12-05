import datetime
import decimal
import json
import uuid

from bson import ObjectId


class jsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()+'Z'
        elif isinstance(o, datetime.date):
            return o.isoformat() + 'T00:00:00Z'
        elif isinstance(o, datetime.time):
            r = o.isoformat()
            if o.microsecond:
                r = r[:12]
            return r

        elif isinstance(o, (dict, list, tuple, str, int, float, bool, type(None))):
            return super().default(o)
        else:
            return str(o)


def json_decoder(value):
    if isinstance(value, dict):
        for k, v in value.items():
            value[k] = json_decoder(v)
    elif isinstance(value, list):
        for index, row in enumerate(value):
            value[index] = json_decoder(row)
    elif isinstance(value, str) and value:
        try:
            value = datetime.datetime.fromisoformat(value)
        except:
            pass

        try:
            value = ObjectId(value)
        except:
            pass

        try:
            value = decimal.Decimal(value)
        except:
            pass
        try:
            value = uuid.UUID(value)
        except:
            pass
    return value
