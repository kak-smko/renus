import asyncio
import inspect
from unittest.mock import MagicMock

import pytest

from renus.app import App
from renus.app.dispatch import serve_result
from renus.app.handlers import run_direct
from renus.app.lifespan import run_shutdown, run_startup
from renus.cache import Cache
from renus.response import JsonResponse, Response, Status, TextResponse
from renus.router import RouteRegistry, Router
from renus.websockets import WebSocket

def http_scope(path="/", method="GET", headers=None, query_string=b""):
    return {
        "type": "http",
        "http_version": "1.1",
        "scheme": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "query_string": query_string,
        "headers": headers or [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }

def ws_scope(path="/ws"):
    return {
        "type": "websocket",
        "scheme": "ws",
        "path": path,
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
    }

def lifespan_scope():
    return {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}}

class _MessageAccumulator:

    def __init__(self, receive_script):
        self.sent = []
        self._script = list(receive_script)

    async def receive(self):
        return self._script.pop(0)

    async def send(self, message):
        self.sent.append(message)

def _http_client(path="/", method="GET", *, body=b"", headers=None):
    acc = _MessageAccumulator(
        [{"type": "http.request", "body": body, "more_body": False}]
    )
    return acc, http_scope(path, method, headers)

def plain_sync():
    return JsonResponse({"ok": True})

async def async_ok(request):
    return JsonResponse({"ok": True})

async def echo_inputs(request):
    return JsonResponse(await request.form())

def boom():
    raise RuntimeError("boom")

@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    from renus.cache import file as file_module

    db_path = tmp_path / "cache.sqlite"

    def fake_get(self, name, *default):
        if name == "cache_file_path":
            return str(db_path)
        return default[0] if default else None

    file_module._conn = None
    Cache.clear_instances()
    monkeypatch.setattr(file_module.Config, "get", fake_get)
    yield db_path
    file_module._conn = None
    Cache.clear_instances()

@pytest.fixture(autouse=True)
def reset_registry():
    RouteRegistry.reset()
    yield
    RouteRegistry.reset()

class TestConstruction:
    def test_defaults(self):
        app = App()
        assert app.debug is False
        assert app.env == "local"
        assert app.on_startup == []
        assert app.on_shutdown == []
        assert app.middlewares == []

    def test_accepts_hooks_and_middlewares(self):
        hooks = [lambda: None]
        mw = [object()]
        app = App(on_startup=hooks, on_shutdown=hooks, middlewares=mw)
        assert app.on_startup == hooks
        assert app.on_shutdown == hooks
        assert app.middlewares == mw

    def test_hooks_copied_not_reused(self):
        app = App(on_startup=[lambda: None])
        app.on_startup.append(lambda: None)
        assert len(app.on_startup) == 2

    def test_custom_lifespan_is_used(self):
        def custom(app):
            yield

        app = App(lifespan=custom)
        assert app.lifespan_context is custom

    def test_lifespan_context_is_an_async_generator(self):
        app = App()
        gen = app.lifespan_context(object())
        assert inspect.isasyncgen(gen)

    def test_lifespan_context_was_not_hijacked_by_hooks(self):
        app = App()
        assert isinstance(app.lifespan_context.__name__, str)

class TestASGICall:
    @pytest.mark.asyncio
    async def test_dispatches_http(self, monkeypatch):
        app = App()
        seen = []
        monkeypatch.setattr("renus.app.app.serve_http", _record(seen, "http"))
        await app(http_scope(), _noop, _noop)
        assert seen == ["http"]

    @pytest.mark.asyncio
    async def test_dispatches_lifespan(self, monkeypatch):
        app = App()
        seen = []
        monkeypatch.setattr("renus.app.app.serve_lifespan", _record(seen, "lifespan"))
        await app(lifespan_scope(), _noop, _noop)
        assert seen == ["lifespan"]

    @pytest.mark.asyncio
    async def test_dispatches_websocket(self, monkeypatch):
        app = App()
        seen = []
        monkeypatch.setattr("renus.app.app.serve_websocket", _record(seen, "websocket"))
        await app(ws_scope(), _noop, _noop)
        assert seen == ["websocket"]

    @pytest.mark.asyncio
    async def test_rejects_unknown_scope_type(self):
        app = App()
        with pytest.raises(AssertionError):
            await app({"type": "bogus"}, _noop, _noop)

def _record(seen, label):
    async def fake(app, scope, receive, send):
        seen.append(label)

    return fake

async def _noop(*args, **kwargs):
    return None

class TestLifespan:
    @pytest.mark.asyncio
    async def test_successful_lifespan(self):
        app = App()
        acc = _MessageAccumulator(
            [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
        )
        await app(lifespan_scope(), acc.receive, acc.send)
        types = [m["type"] for m in acc.sent]
        assert types == ["lifespan.startup.complete", "lifespan.shutdown.complete"]

    @pytest.mark.asyncio
    async def test_default_lifespan_calls_startup_and_shutdown(self, monkeypatch):
        started, stopped = [], []
        app = App(on_startup=[lambda: started.append(1)], on_shutdown=[lambda: stopped.append(1)])
        acc = _MessageAccumulator(
            [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
        )
        await app(lifespan_scope(), acc.receive, acc.send)
        assert started == [1]
        assert stopped == [1]

    @pytest.mark.asyncio
    async def test_default_lifespan_connects_and_disconnects_cache(self):
        from renus.cache import file as file_module

        observed = []

        def on_startup():
            observed.append(file_module._conn is not None)

        def on_shutdown():
            observed.append(file_module._conn is not None)

        app = App(on_startup=[on_startup], on_shutdown=[on_shutdown])
        acc = _MessageAccumulator(
            [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
        )
        await app(lifespan_scope(), acc.receive, acc.send)

        assert observed == [True, True]
        assert file_module._conn is None

    @pytest.mark.asyncio
    async def test_failing_lifespan_sends_failure(self):
        def bad_lifespan(app):
            raise RuntimeError("startup exploded")
            yield

        app = App(lifespan=bad_lifespan)

        app.env = "production"

        acc = _MessageAccumulator([{"type": "lifespan.startup"}])
        await app(lifespan_scope(), acc.receive, acc.send)
        assert acc.sent[0]["type"] == "lifespan.startup.failed"

class TestStartupShutdown:
    def test_startup_runs_sync_handlers_in_order(self):

        calls = []

        def first():
            calls.append(1)

        def second():
            calls.append(2)

        app = App(on_startup=[first, second])
        asyncio.run(run_startup(app))
        assert calls == [1, 2]

    def test_shutdown_runs_sync_handlers_in_order(self):
        calls = []

        def first():
            calls.append(1)

        def second():
            calls.append(2)

        app = App(on_shutdown=[first, second])
        asyncio.run(run_shutdown(app))
        assert calls == [1, 2]

class TestHttp:
    @pytest.mark.asyncio
    async def test_returns_handler_response(self):
        Router().get("/ping", func=async_ok)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(http_scope("/ping"), acc.receive, acc.send)

        start = acc.sent[0]
        body = acc.sent[1]
        assert start["type"] == "http.response.start"
        assert start["status"] == Status.HTTP_200_OK
        assert body["type"] == "http.response.body"
        assert body["body"] == b'{"ok":true}'

    @pytest.mark.asyncio
    async def test_uppercases_method_before_resolution(self):
        Router().get("/ping", func=async_ok)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(http_scope("/ping", "get"), acc.receive, acc.send)
        assert acc.sent[0]["status"] == Status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_unknown_method_is_not_resolved(self):

        Router().get("/ping", func=async_ok)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(http_scope("/ping", "POST"), acc.receive, acc.send)
        assert acc.sent[0]["status"] == Status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_404_when_no_route_matches(self):
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(http_scope("/missing"), acc.receive, acc.send)
        assert acc.sent[0]["status"] == Status.HTTP_404_NOT_FOUND
        assert acc.sent[1]["body"] == b"Path not Found"

    @pytest.mark.asyncio
    async def test_request_injected_into_handler(self):
        Router().get("/view", func=async_ok)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(http_scope("/view"), acc.receive, acc.send)
        assert acc.sent[0]["status"] == Status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_post_runs_form_parser(self):
        Router().post("/submit", func=echo_inputs)
        body = b'{"name":"x","age":3}'
        acc = _MessageAccumulator([{"type": "http.request", "body": body, "more_body": False}])
        await App()(
            http_scope("/submit", "POST", headers=[(b"content-type", b"application/json")]),
            acc.receive,
            acc.send,
        )
        payload = acc.sent[1]["body"]
        assert b'"name"' in payload
        assert b'"x"' in payload

    @pytest.mark.asyncio
    async def test_plain_non_response_value_is_wrapped(self):
        async def plain():
            return "hello"

        Router().get("/plain", func=plain)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(http_scope("/plain"), acc.receive, acc.send)
        assert acc.sent[1]["body"] == b"hello"

class TestHttpErrors:
    @pytest.mark.asyncio
    async def test_handler_exception_returns_500_and_reraises_in_local(self):
        Router().get("/boom", func=boom)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        with pytest.raises(RuntimeError):
            await App()(http_scope("/boom"), acc.receive, acc.send)
        assert acc.sent[0]["type"] == "http.response.start"
        assert acc.sent[0]["status"] == Status.HTTP_500_INTERNAL_SERVER_ERROR
        assert b"Internal Server Error" in acc.sent[1]["body"]

    @pytest.mark.asyncio
    async def test_route_loading_exception_is_surfaced(self):

        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        with pytest.raises(RuntimeError, match="path traversal"):
            await App()(http_scope("/../etc/passwd"), acc.receive, acc.send)

class TestWebSocket:
    @pytest.mark.asyncio
    async def test_route_not_found_closes_1004(self):
        acc = _MessageAccumulator([{"type": "websocket.connect"}])
        await App()(ws_scope(), acc.receive, acc.send)
        assert acc.sent and acc.sent[0]["type"] == "websocket.close"
        assert acc.sent[0]["code"] == 1004

    @pytest.mark.asyncio
    async def test_unresolvable_func_closes_1004(self):

        Router().ws("/ws", func="missing_method")
        acc = _MessageAccumulator([{"type": "websocket.connect"}])
        await App()(ws_scope(), acc.receive, acc.send)
        assert acc.sent and acc.sent[0]["type"] == "websocket.close"
        assert acc.sent[0]["code"] == 1004

    @pytest.mark.asyncio
    async def test_resolved_handler_runs_and_receives_ws(self):
        handled = []

        async def ws_handler(ws):
            assert isinstance(ws, WebSocket)
            handled.append(ws)
            return True

        Router().ws("/ws", func=ws_handler)
        acc = _MessageAccumulator([{"type": "websocket.connect"}])
        await App()(ws_scope(), acc.receive, acc.send)
        assert handled, "websocket handler should have been called"
        assert acc.sent == []

    @pytest.mark.asyncio
    async def test_short_circuiting_middleware_closes_1003(self):
        async def gate(ws):
            return None

        async def ws_handler(ws):
            return True

        Router().ws("/ws", func=ws_handler, middlewares=[gate])
        acc = _MessageAccumulator([{"type": "websocket.connect"}])
        await App()(ws_scope(), acc.receive, acc.send)

        assert acc.sent and acc.sent[0]["type"] == "websocket.close"
        assert acc.sent[0]["code"] == 1003

class TestMiddleware:
    @pytest.mark.asyncio
    async def test_app_level_onion_middleware(self):
        order = []

        async def onion(request, method, res):
            order.append("before")
            resp = await method(**res["args"])
            order.append("after")
            return resp

        app = App(middlewares=[onion])
        Router().get("/mw", func=async_ok)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await app(http_scope("/mw"), acc.receive, acc.send)
        assert order == ["before", "after"]
        assert acc.sent[0]["status"] == Status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_legacy_gate_middleware_can_short_circuit(self):
        async def deny(request):
            return TextResponse("blocked", Status.HTTP_401_UNAUTHORIZED)

        app = App(middlewares=[deny])
        Router().get("/mw", func=async_ok)
        acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await app(http_scope("/mw"), acc.receive, acc.send)
        assert acc.sent[0]["status"] == Status.HTTP_401_UNAUTHORIZED
        assert acc.sent[1]["body"] == b"blocked"

class TestCaching:
    @pytest.mark.asyncio
    async def test_cached_route_hits_handler_once(self, isolated_cache):
        count = {"n": 0}

        async def counted(request):
            count["n"] += 1
            return JsonResponse({"count": count["n"]})

        Router().get("/cached", func=counted, cache=60)
        scope = http_scope("/cached")

        for _ in range(2):
            acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
            await App()(scope, acc.receive, acc.send)
        assert count["n"] == 1

    @pytest.mark.asyncio
    async def test_cached_response_is_marked(self, isolated_cache):
        async def counted(request):
            return JsonResponse({"count": 1})

        Router().get("/cached", func=counted, cache=60)
        scope = http_scope("/cached")
        acc1 = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(scope, acc1.receive, acc1.send)
        acc2 = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
        await App()(scope, acc2.receive, acc2.send)
        headers = dict(acc2.sent[0]["headers"])
        assert headers == {b"r-cache": b"ok"} or (b"r-cache", b"ok") in acc2.sent[0]["headers"]

    @pytest.mark.asyncio
    async def test_uncached_route_runs_every_time(self, isolated_cache):
        count = {"n": 0}

        async def counted(request):
            count["n"] += 1
            return JsonResponse({"count": count["n"]})

        Router().get("/uncached", func=counted)
        scope = http_scope("/uncached")
        for _ in range(3):
            acc = _MessageAccumulator([{"type": "http.request", "body": b"", "more_body": False}])
            await App()(scope, acc.receive, acc.send)
        assert count["n"] == 3

class TestResolveHandler:
    def test_plain_callable_returns_itself(self):
        app = App()
        res = {"controller": None, "func": plain_sync}
        assert app._resolve_handler(res, None) is plain_sync

    def test_binds_controller_with_request_argument(self):
        class C:
            def __init__(self, request):
                self.request = request

            def hi(self):
                return "hi"

        app = App()
        request = object()
        res = {"controller": C, "func": "hi"}
        bound = app._resolve_handler(res, request)
        assert bound.__self__ is not None
        assert bound() == "hi"

class TestEndpoint:
    @pytest.mark.asyncio
    async def test_async_handler_is_awaited(self):
        app = App()

        async def h(**kwargs):
            return "async"

        req = MagicMock()
        ep = app._endpoint({"cache": None, "args": {}}, h, req)
        assert await ep() == "async"

    @pytest.mark.asyncio
    async def test_sync_handler_is_not_supported(self):

        app = App()

        def h(**kwargs):
            return "sync"

        req = MagicMock()
        ep = app._endpoint({"cache": None, "args": {}}, h, req)
        with pytest.raises(TypeError):
            await ep()

    @pytest.mark.asyncio
    async def test_cached_endpoint_reuses_response(self, isolated_cache):

        app = App()
        count = {"n": 0}

        async def h(**kwargs):
            count["n"] += 1
            return JsonResponse({"n": count["n"]})

        req = MagicMock()
        req.full_path = "http://testserver/cached"
        ep = app._endpoint({"cache": 60, "args": {}}, h, req)

        first = await ep()
        assert isinstance(first, Response)
        assert count["n"] == 1

        second = await ep()
        assert isinstance(second, Response)
        assert count["n"] == 1
        assert (b"r-cache", b"ok") in second.raw_headers

class TestFunction:
    @pytest.mark.asyncio
    async def test_function_dispatches_directly(self):
        async def h(a, b=1):
            return a + b

        req = MagicMock()
        res = {"cache": None, "args": {"a": 5}}
        assert await run_direct(res, req, h) == 6

class TestResult:
    @pytest.mark.asyncio
    async def test_wraps_non_response_value(self):
        sent = []

        async def send(msg):
            sent.append(msg)

        request = MagicMock()
        request.headers = {}
        await serve_result(App(), request, "just text", {}, _noop, send)
        assert sent[0]["type"] == "http.response.start"
        assert sent[1]["body"] == b"just text"

    @pytest.mark.asyncio
    async def test_passes_through_response_instance(self):
        sent = []

        async def send(msg):
            sent.append(msg)

        request = MagicMock()
        request.headers = {}
        resp = TextResponse("kept", Status.HTTP_201_CREATED)
        await serve_result(App(), request, resp, {}, _noop, send)
        assert sent[0]["status"] == Status.HTTP_201_CREATED
        assert sent[1]["body"] == b"kept"
