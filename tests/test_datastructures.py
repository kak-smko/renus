import io
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from renus.datastructures import (
    MAX_UPLOAD_SIZE,
    JSONEncoder,
    Background,
    FormData,
    MultiDict,
    UploadFile,
    dumps,
    jsonEncoder,
    json_decoder,
    loads,
)

def _sync_upload():
    return UploadFile(filename="a.txt", file=io.BytesIO(b""), content_type="text/plain")

def test_multidict_from_pairs():
    md = MultiDict([("a", 1), ("b", 2)])
    assert md["a"] == 1
    assert md["b"] == 2
    assert len(md) == 2

def test_multidict_from_mapping_and_kwargs():
    md = MultiDict({"a": 1}, b=2)
    assert md["a"] == 1
    assert md["b"] == 2

def test_multidict_duplicate_keys_keep_order():
    md = MultiDict([("a", 1), ("a", 2)])
    assert md.multi_items() == [("a", 1), ("a", 2)]

    assert md["a"] == 2
    assert md.get("a") == 2
    assert md.getlist("a") == [1, 2]

def test_multidict_mapping_protocol():
    md = MultiDict(a=1, b=2)
    assert sorted(md.keys()) == ["a", "b"]
    assert sorted(md.values()) == [1, 2]
    assert "a" in md and "z" not in md
    assert set(iter(md)) == {"a", "b"}
    assert sorted(md.items()) == [("a", 1), ("b", 2)]

def test_multidict_get_default():
    md = MultiDict(a=1)
    assert md.get("missing") is None
    assert md.get("missing", 42) == 42

def test_multidict_dedupe_self():
    md = MultiDict([("a", 1), ("a", 2)])
    md2 = MultiDict(md)
    assert md2.multi_items() == [("a", 1), ("a", 2)]

def test_multidict_bool():
    assert not MultiDict()
    assert not MultiDict([])
    assert MultiDict(a=1)
    assert MultiDict([("a", 1), ("b", 2)])

    assert MultiDict([("a", 1), ("a", 2)])

def test_multidict_eq_is_order_independent_but_count_aware():

    assert MultiDict([("a", 1), ("b", 2)]) == MultiDict([("b", 2), ("a", 1)])

    assert MultiDict([("a", 1), ("a", 2)]) != MultiDict([("a", 1)])
    assert MultiDict([("a", 1), ("a", 2)]) == MultiDict([("a", 2), ("a", 1)])

def test_multidict_eq_with_plain_mapping():
    assert MultiDict(a=1, b=2) == {"a": 1, "b": 2}
    assert MultiDict([("a", 1), ("a", 2)]) != {"a": 2}

def test_multidict_copy_is_independent():
    md = MultiDict([("a", 1), ("a", 2)])
    cp = md.copy()
    assert cp == md
    assert cp is not md

    assert cp.multi_items() == md.multi_items()

def test_multidict_union():
    left = MultiDict([("a", 1), ("a", 2)])
    right = {"b": 3}
    merged = left | right
    assert isinstance(merged, MultiDict)
    assert merged.multi_items() == [("a", 1), ("a", 2), ("b", 3)]

    assert left.multi_items() == [("a", 1), ("a", 2)]

def test_multidict_eq_repr_copy():
    m1 = MultiDict(a=1, b=2)
    m2 = MultiDict([("a", 1), ("b", 2)])
    assert m1 == m2
    assert m1 != MultiDict(a=1)
    assert "MultiDict" in repr(m1)
    assert m1.__copy__() == m1

def test_formdata_string_fields():
    fd = FormData([("name", "renus"), ("role", "dev")])
    assert fd["name"] == "renus"
    assert fd["role"] == "dev"

def test_formdata_mixed_upload():
    uf = _sync_upload()
    fd = FormData([("title", "doc"), ("file", uf)])
    assert fd["title"] == "doc"
    assert fd["file"] is uf
    assert isinstance(fd["file"], UploadFile)

def test_formdata_multiple_files():
    u1, u2 = _sync_upload(), _sync_upload()
    fd = FormData([("file", u1), ("file", u2)])
    assert fd.getlist("file") == [u1, u2]
    assert fd["file"] is u2

@pytest.mark.asyncio
async def test_formdata_close_closes_uploads():
    uf = _sync_upload()
    fd = FormData([("file", uf)])
    assert uf.file.closed is False
    await fd.close()
    assert uf.file.closed is True

@pytest.mark.asyncio
async def test_uploadfile_write_read_seek():
    uf = _sync_upload()
    await uf.write(b"hello world")
    await uf.seek(0)
    assert await uf.read() == b"hello world"

@pytest.mark.asyncio
async def test_uploadfile_partial_read():
    uf = _sync_upload()
    await uf.write(b"hello world")
    await uf.seek(3)
    assert await uf.read(5) == b"lo wo"

def test_uploadfile_autocreate_spools_in_memory():
    uf = UploadFile(filename="x.bin")
    assert uf.filename == "x.bin"
    assert uf.content_type == ""
    assert uf._in_memory is True
    uf.file.close()

def test_uploadfile_content_type():
    uf = UploadFile(filename="x.html", content_type="text/html")
    assert uf.content_type == "text/html"

@pytest.mark.asyncio
async def test_uploadfile_size_property():
    uf = _sync_upload()
    await uf.write(b"0123456789")
    await uf.seek(0)
    assert uf.size == 10

    await uf.seek(3)
    assert uf.size == 7

@pytest.mark.asyncio
async def test_uploadfile_async_context_manager():
    uf = _sync_upload()
    async with uf as handler:
        assert handler is uf
        await handler.write(b"xyz")
    assert uf.file.closed is True

def test_uploadfile_repr():
    uf = _sync_upload()
    assert "UploadFile" in repr(uf)
    assert "a.txt" in repr(uf)

def test_max_upload_size_config_default():
    assert MAX_UPLOAD_SIZE == 50 * 1024 * 1024


@pytest.mark.asyncio
async def test_background_runs_async_callable():
    async def fn(x):
        return x * 2

    bg = Background(fn, 21)
    result = await bg()

    assert result is None

@pytest.mark.asyncio
async def test_background_run_returns_result():
    async def afn(x):
        return x * 2

    async def sfn(x):
        return x + 1

    assert await Background(afn, 21).run() == 42
    assert await Background(sfn, 41).run() == 42

def test_background_repr():
    def fn():
        pass

    assert "Background" in repr(Background(fn))

def test_json_encoder_datetime():
    assert jsonEncoder().encode(datetime(2024, 1, 2, 3, 4, 5)) == '"2024-01-02T03:04:05Z"'

    assert jsonEncoder().encode(date(2024, 1, 2)) == '"2024-01-02T00:00:00Z"'

def test_json_encoder_aware_datetime_normalizes_to_utc():
    aware = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2)))
    assert jsonEncoder().encode(aware) == '"2024-01-02T01:04:05Z"'
    utc = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert jsonEncoder().encode(utc) == '"2024-01-02T03:04:05Z"'

def test_json_encoder_time():
    encoded = jsonEncoder().encode(time(12, 30, 45))
    assert encoded == '"12:30:45"'
    micro = jsonEncoder().encode(time(12, 30, 45, 123456))
    assert micro == '"12:30:45.123456"'

def test_json_encoder_uuid_decimal_set():
    u = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert jsonEncoder().encode(u) == '"12345678-1234-5678-1234-567812345678"'
    assert jsonEncoder().encode(Decimal("1.5")) == '"1.5"'
    assert jsonEncoder().encode({3, 1, 2}) == '[1, 2, 3]'

def test_json_encoder_object():
    class Obj:
        def __init__(self):
            self.a = 1

    assert jsonEncoder().encode(Obj()) == '{"a": 1}'

def test_json_encoder_alias():
    assert JSONEncoder is jsonEncoder

def test_dumps_loads_roundtrip_datetime():
    data = {"when": datetime(2024, 6, 1, 12, 0, 0)}
    raw = dumps(data)
    assert '"when":"2024-06-01T12:00:00Z"' in raw
    back = loads(raw)
    assert back["when"] == datetime(2024, 6, 1, 12, 0, 0)

def test_dumps_loads_roundtrip_uuid_decimal():
    u = uuid.UUID("12345678-1234-5678-1234-567812345678")
    data = {"id": u, "price": Decimal("19.99")}
    raw = dumps(data)
    back = loads(raw)
    assert back["id"] == u
    assert back["price"] == Decimal("19.99")

def test_json_decoder_passthrough_scalars():
    assert json_decoder(None) is None
    assert json_decoder(3) == 3
    assert json_decoder(True) is True
    assert json_decoder("not-special") == "not-special"

def test_json_decoder_recursive():
    assert json_decoder({"a": {"b": "2024-01-01T00:00:00"}}) == {
        "a": {"b": datetime(2024, 1, 1)}
    }
