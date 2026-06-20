import datetime
import decimal
import json
import uuid
import re

try:
    from bson import ObjectId
except:
    def ObjectId(s):
        raise

_ISOFORMAT_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}')
_OBJECTID_RE = re.compile(r'^[a-fA-F0-9]{24}$')
_UUID_RE = re.compile(
    r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$'
)
_DECIMAL_RE = re.compile(r'^-?\d+\.\d+$')

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
        elif hasattr(o, '__dict__'):
            return dict(o)
        else:
            return str(o)


def json_decoder(value):
    if isinstance(value, dict):
        return {k: json_decoder(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [json_decoder(item) for item in value]
    elif isinstance(value, str) and value:
        return _decode_string(value)
    return value

def _decode_string(value: str):
    length = len(value)

    # Check datetime (min length for ISO format is 19: "2024-01-01T00:00:00")
    if length >= 19 and _ISOFORMAT_RE.match(value):
        try:
            clean = value.rstrip('Z')
            return datetime.datetime.fromisoformat(clean)
        except (ValueError, TypeError):
            pass

    # Check ObjectId (exactly 24 hex chars)
    if length == 24 and _OBJECTID_RE.match(value):
        if ObjectId is not None:
            try:
                return ObjectId(value)
            except Exception:
                pass

    # Check UUID (exactly 36 chars: 8-4-4-4-12)
    if length == 36 and _UUID_RE.match(value):
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError):
            pass

    # Check Decimal (only for numeric-looking strings with decimal point)
    if length >= 3 and _DECIMAL_RE.match(value):
        try:
            return decimal.Decimal(value)
        except (decimal.InvalidOperation, ValueError):
            pass

    return value