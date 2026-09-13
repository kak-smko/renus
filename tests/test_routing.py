from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

try:
    from bson.objectid import ObjectId
except ImportError:
    ObjectId = None

from renus.router import (
    CONVERTOR_TYPES,
    Middleware,
    Router,
    RouteRegistry,
    build_path,
    full_path_builder,
    is_safe_path,
)

def _create_mock_controller():
    controller = MagicMock()
    controller.index = MagicMock(return_value="index_result")
    controller.store = MagicMock(return_value="store_result")
    controller.update = MagicMock(return_value="update_result")
    controller.delete = MagicMock(return_value="delete_result")
    controller.__name__ = "MockController"
    return controller

def _create_mock_request(method="GET", subdomain="_"):
    request = MagicMock()
    request.method = method
    request.subdomain = subdomain
    return request

@pytest.fixture(autouse=True)
def reset_registry():
    RouteRegistry.reset()
    yield
    RouteRegistry.reset()

class TestRouteRegistry:

    def test_singleton_returns_same_instance(self):
        registry1 = RouteRegistry()
        registry2 = RouteRegistry()
        assert registry1 is registry2

    def test_register_route(self):
        registry = RouteRegistry()
        route_entry = {
            "path": "/users",
            "controller": None,
            "func": "index",
            "middlewares": [],
            "regex": build_path("/users"),
        }
        registry.register("_", "GET", route_entry)

        assert "_" in registry.all
        assert "GET" in registry.all["_"]
        assert len(registry.all["_"]["GET"]) == 1
        assert registry.all["_"]["GET"][0]["path"] == "/users"

    def test_resolve_basic_route(self):
        registry = RouteRegistry()
        controller = _create_mock_controller()
        route_entry = {
            "path": "/users",
            "controller": controller,
            "func": "index",
            "middlewares": [],
            "regex": build_path("/users"),
        }
        registry.register("_", "GET", route_entry)

        request = _create_mock_request("GET", "_")
        scope = {"path": "/users"}
        result = registry.resolve(request, scope)

        assert result is not None
        assert result["path"] == "/users"
        assert result["controller"] is controller
        assert result["func"] == "index"
        assert result["args"] == {}

    def test_resolve_with_parameters(self):
        registry = RouteRegistry()
        controller = _create_mock_controller()
        route_entry = {
            "path": "/users/{id:int}",
            "controller": controller,
            "func": "show",
            "middlewares": [],
            "regex": build_path("/users/{id:int}"),
        }
        registry.register("_", "GET", route_entry)

        request = _create_mock_request("GET", "_")
        scope = {"path": "/users/123"}
        result = registry.resolve(request, scope)

        assert result is not None
        assert result["args"]["id"] == 123
        assert isinstance(result["args"]["id"], int)

    def test_resolve_not_found(self):
        registry = RouteRegistry()
        request = _create_mock_request("GET", "_")
        scope = {"path": "/nonexistent"}
        result = registry.resolve(request, scope)

        assert result is None

    def test_resolve_wrong_method(self):
        registry = RouteRegistry()
        route_entry = {
            "path": "/users",
            "controller": None,
            "func": "index",
            "middlewares": [],
            "regex": build_path("/users"),
        }
        registry.register("_", "GET", route_entry)

        request = _create_mock_request("POST", "_")
        scope = {"path": "/users"}
        result = registry.resolve(request, scope)

        assert result is None

    def test_subdomains_list(self):
        registry = RouteRegistry()
        route_entry = {
            "path": "/users",
            "controller": None,
            "func": "index",
            "middlewares": [],
            "regex": build_path("/users"),
        }
        registry.register("api", "GET", route_entry)
        registry.register("admin", "GET", route_entry)

        subdomains = registry.subdomains
        assert "api" in subdomains
        assert "admin" in subdomains

    def test_summary_output(self):
        registry = RouteRegistry()
        route_entry = {
            "path": "/users",
            "controller": None,
            "func": "index",
            "middlewares": [],
            "regex": build_path("/users"),
        }
        registry.register("_", "GET", route_entry)

        summary = registry.summary()
        assert "Route Registry" in summary
        assert "1 routes registered" in summary
        assert "/users" in summary

    def test_clear_registry(self):
        registry = RouteRegistry()
        route_entry = {
            "path": "/users",
            "controller": None,
            "func": "index",
            "middlewares": [],
            "regex": build_path("/users"),
        }
        registry.register("_", "GET", route_entry)

        assert len(registry.all) > 0
        registry.clear()
        assert len(registry.all) == 0

class TestRouteParameters:

    def test_string_parameter(self):
        regex, params = build_path("/users/{name:str}")
        match = regex.fullmatch("/users/john")
        assert match is not None
        assert params["name"].convert(match.group("name")) == "john"

    def test_string_parameter2(self):
        regex, params = build_path("/users/{name}")
        match = regex.fullmatch("/users/john")
        assert match is not None
        assert params["name"].convert(match.group("name")) == "john"

    def test_integer_parameter(self):
        regex, params = build_path("/users/{id:int}")
        match = regex.fullmatch("/users/123")
        assert match is not None
        assert params["id"].convert(match.group("id")) == 123

        match = regex.fullmatch("/users/abc")
        assert match is None

    def test_float_parameter(self):
        regex, params = build_path("/price/{value:float}")

        match = regex.fullmatch("/price/19.99")
        assert match is not None
        assert params["value"].convert(match.group("value")) == 19.99

        match = regex.fullmatch("/price/42")
        assert match is not None
        assert params["value"].convert(match.group("value")) == 42.0

    @pytest.mark.skipif(
        ObjectId is None, reason="bson not installed; oid convertor unavailable"
    )
    def test_oid_parameter(self):
        regex, params = build_path("/users/{id:oid}")
        match = regex.fullmatch("/users/507f1f77bcf86cd799439011")
        assert match is not None
        assert params["id"].convert(match.group("id")) == ObjectId(
            "507f1f77bcf86cd799439011"
        )

        match = regex.fullmatch("/users/invalid")
        assert match is None

    def test_bool_parameter(self):
        regex, params = build_path("/active/{flag:bool}")

        match = regex.fullmatch("/active/true")
        assert match is not None
        assert params["flag"].convert(match.group("flag")) is True

        match = regex.fullmatch("/active/false")
        assert match is not None
        assert params["flag"].convert(match.group("flag")) is False

        match = regex.fullmatch("/active/yes")
        assert match is None

    def test_path_parameter(self):
        regex, params = build_path("/files/{filepath:path}")
        match = regex.fullmatch("/files/docs/reports/2024.pdf")
        assert match is not None
        assert (
            params["filepath"].convert(match.group("filepath"))
            == "docs/reports/2024.pdf"
        )

    def test_multiple_parameters(self):
        regex, params = build_path("/users/{id:int}/posts/{slug:str}")
        match = regex.fullmatch("/users/42/posts/hello-world")

        assert match is not None
        assert params["id"].convert(match.group("id")) == 42
        assert params["slug"].convert(match.group("slug")) == "hello-world"

    def test_uuid_parameter(self):
        regex, params = build_path("/users/{id:uuid}")

        raw = "550e8400-e29b-41d4-a716-446655440000"
        match = regex.fullmatch(f"/users/{raw}")
        assert match is not None
        assert params["id"].convert(match.group("id")) == UUID(raw)

        assert regex.fullmatch("/users/not-a-uuid") is None

    def test_unknown_convertor_raises(self):
        with pytest.raises(ValueError, match="Unknown route parameter type 'unknown'"):
            build_path("/users/{id:unknown}")

class TestRouter:

    def test_router_initialization(self):
        router = Router()
        assert router._prefix == ""
        assert router._middlewares == []
        assert router._subdomain == "_"
        assert router._registry is not None

    def test_get_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.get("/users", controller, "index")

        registry = RouteRegistry()
        assert "GET" in registry.all["_"]
        assert len(registry.all["_"]["GET"]) == 1

    def test_post_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.post("/users", controller, "store")

        registry = RouteRegistry()
        assert "POST" in registry.all["_"]
        assert len(registry.all["_"]["POST"]) == 1

    def test_put_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.put("/users/{id:int}", controller, "update")

        registry = RouteRegistry()
        assert "PUT" in registry.all["_"]
        assert len(registry.all["_"]["PUT"]) == 1

    def test_delete_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.delete("/users/{id:int}", controller, "delete")

        registry = RouteRegistry()
        assert "DELETE" in registry.all["_"]
        assert len(registry.all["_"]["DELETE"]) == 1

    def test_head_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.head("/users", controller, "head")

        registry = RouteRegistry()
        assert "HEAD" in registry.all["_"]
        assert len(registry.all["_"]["HEAD"]) == 1

    def test_option_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.option("/users", controller, "options")

        registry = RouteRegistry()
        assert "OPTIONS" in registry.all["_"]
        assert len(registry.all["_"]["OPTIONS"]) == 1

    def test_ws_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.ws("/chat", controller, "handle")

        registry = RouteRegistry()
        assert "WS" in registry.all["_"]
        assert len(registry.all["_"]["WS"]) == 1

    def test_crud_generation(self):
        router = Router()
        controller = _create_mock_controller()
        router.crud("/users", controller)

        registry = RouteRegistry()

        assert "GET" in registry.all["_"]
        get_routes = [r for r in registry.all["_"]["GET"] if r["path"] == "/users"]
        assert len(get_routes) == 1
        assert get_routes[0]["func"] == "index"

        assert "POST" in registry.all["_"]
        post_routes = [r for r in registry.all["_"]["POST"] if r["path"] == "/users"]
        assert len(post_routes) == 1
        assert post_routes[0]["func"] == "store"

        assert "PUT" in registry.all["_"]
        put_routes = [
            r for r in registry.all["_"]["PUT"] if r["path"] == "/users/{id:oid}"
        ]
        assert len(put_routes) == 1
        assert put_routes[0]["func"] == "update"

        assert "DELETE" in registry.all["_"]
        delete_routes = [
            r for r in registry.all["_"]["DELETE"] if r["path"] == "/users/{id:oid}"
        ]
        assert len(delete_routes) == 1
        assert delete_routes[0]["func"] == "delete"

    def test_mcud_generation(self):
        router = Router()
        controller = _create_mock_controller()
        router.mcud("/users", controller)

        registry = RouteRegistry()

        assert "POST" in registry.all["_"]
        post_routes = [r for r in registry.all["_"]["POST"] if r["path"] == "/users"]
        assert len(post_routes) == 1
        assert post_routes[0]["func"] == "m_store"

        assert "PUT" in registry.all["_"]
        put_routes = [r for r in registry.all["_"]["PUT"] if r["path"] == "/users"]
        assert len(put_routes) == 1
        assert put_routes[0]["func"] == "m_update"

        assert "DELETE" in registry.all["_"]
        delete_routes = [
            r for r in registry.all["_"]["DELETE"] if r["path"] == "/users"
        ]
        assert len(delete_routes) == 1
        assert delete_routes[0]["func"] == "m_delete"

    def test_router_with_prefix(self):
        router = Router(prefix="/api/v1")
        controller = _create_mock_controller()
        router.get("/users", controller, "index")

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert routes[0]["path"] == "/api/v1/users"

    def test_router_with_middlewares(self):
        middleware1 = MagicMock()
        middleware2 = MagicMock()
        router = Router(middlewares=[middleware1])
        controller = _create_mock_controller()
        router.get("/users", controller, "index", middlewares=[middleware2])

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert middleware1 in routes[0]["middlewares"]
        assert middleware2 in routes[0]["middlewares"]

    def test_router_with_subdomain(self):
        router = Router(subdomain="api")
        controller = _create_mock_controller()
        router.get("/users", controller, "index")

        registry = RouteRegistry()
        assert "api" in registry.all
        assert "GET" in registry.all["api"]

    def test_subdomain_underscore_raises_error(self):
        with pytest.raises(ValueError, match="subdomain cannot be '_'"):
            Router(subdomain="_")

class TestRouterGroups:

    def test_context_manager_basic(self):
        router = Router()
        with router as r:
            assert r is router

    def test_group_prefix_concatenation(self):
        router = Router(prefix="/api")
        group = router.group("/v1")

        controller = _create_mock_controller()
        group.get("/users", controller, "index")

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert routes[0]["path"] == "/api/v1/users"

    def test_group_middleware_inheritance(self):
        middleware1 = MagicMock()
        middleware2 = MagicMock()

        router = Router(middlewares=[middleware1])
        group = router.group("/admin", middlewares=[middleware2])

        controller = _create_mock_controller()
        group.get("/users", controller, "index")

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert middleware1 in routes[0]["middlewares"]
        assert middleware2 in routes[0]["middlewares"]

    def test_nested_groups(self):
        router = Router(prefix="/api")
        v1_group = router.group("/v1")
        admin_group = v1_group.group("/admin")

        controller = _create_mock_controller()
        admin_group.get("/users", controller, "index")

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert routes[0]["path"] == "/api/v1/admin/users"

    def test_deeply_nested_groups(self):
        router = Router()
        level1 = router.group("/api")
        level2 = level1.group("/v1")
        level3 = level2.group("/admin")
        level4 = level3.group("/reports")

        controller = _create_mock_controller()
        level4.get("/daily", controller, "index")

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert routes[0]["path"] == "/api/v1/admin/reports/daily"

    def test_multiple_groups_same_level(self):
        router = Router(prefix="/api")
        public_group = router.group("/public")
        admin_group = router.group("/admin")

        controller = _create_mock_controller()
        public_group.get("/posts", controller, "index")
        admin_group.get("/users", controller, "index")

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        paths = [r["path"] for r in routes]
        assert "/api/public/posts" in paths
        assert "/api/admin/users" in paths

    def test_subdomain_inheritance_in_groups(self):
        router = Router(subdomain="api")
        group = router.group("/v1")

        controller = _create_mock_controller()
        group.get("/users", controller, "index")

        registry = RouteRegistry()
        assert "api" in registry.all
        assert "GET" in registry.all["api"]

class TestPathSafety:

    def test_safe_paths(self):
        assert is_safe_path("/users") is True
        assert is_safe_path("/api/v1/users") is True
        assert is_safe_path("/files/documents/report.pdf") is True

    def test_path_traversal_blocked(self):
        assert is_safe_path("/users/../admin") is False
        assert is_safe_path("/../etc/passwd") is False
        assert is_safe_path("/files/../../secrets") is False

    def test_null_byte_injection_blocked(self):
        assert is_safe_path("/users\0admin") is False
        assert is_safe_path("/files/test.txt\0.exe") is False

    def test_safety_enforced_in_resolution(self):
        registry = RouteRegistry()
        route_entry = {
            "path": "/users",
            "controller": None,
            "func": "index",
            "middlewares": [],
            "regex": build_path("/users"),
        }
        registry.register("_", "GET", route_entry)

        request = _create_mock_request("GET", "_")
        scope = {"path": "/../admin"}

        with pytest.raises(RuntimeError, match="Invalid path: path traversal detected"):
            registry.resolve(request, scope)

class TestCacheConfiguration:

    def test_cache_on_get_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.get("/users", controller, "index", cache=300)

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert routes[0]["cache"] == 300

    def test_no_cache_on_post_route(self):
        router = Router()
        controller = _create_mock_controller()
        router.post("/users", controller, "store")

        registry = RouteRegistry()
        routes = registry.all["_"]["POST"]
        assert "cache" not in routes[0] or routes[0].get("cache") is None

class TestHelperFunctions:

    def test_full_path_builder_with_both(self):
        result = full_path_builder("/api", "/users")
        assert result == "/api/users"

    def test_full_path_builder_with_trailing_slashes(self):
        result = full_path_builder("/api/", "/users/")
        assert result == "/api/users"

    def test_full_path_builder_empty_prefix(self):
        result = full_path_builder("", "/users")
        assert result == "/users"

    def test_full_path_builder_empty_path(self):
        result = full_path_builder("/api", "")
        assert result == "/api"

    def test_full_path_builder_both_empty(self):
        result = full_path_builder("", "")
        assert result == "/"

    def test_build_path_no_parameters(self):
        regex, params = build_path("/users")
        assert regex.fullmatch("/users") is not None
        assert len(params) == 0

    def test_build_path_with_parameters(self):
        regex, params = build_path("/users/{id:int}/posts/{slug:str}")
        assert "id" in params
        assert "slug" in params
        assert params["id"] is CONVERTOR_TYPES["int"]
        assert params["slug"] is CONVERTOR_TYPES["str"]

class TestAppRouteDecorator:

    def _app(self):
        return __import__("renus.app", fromlist=["App"]).App()

    def test_route_registers_in_registry(self):
        import renus.app as app_mod

        app = app_mod.App()

        @app.route("/")
        async def read_root():
            return "root"

        registry = RouteRegistry()
        routes = registry.all["_"]["GET"]
        assert len(routes) == 1
        assert routes[0]["path"] == "/"
        assert routes[0]["func"] is read_root
        assert routes[0]["controller"] is None
        assert routes[0]["middlewares"] == []

    def test_route_defaults_method_to_get(self):
        import renus.app as app_mod

        app = app_mod.App()

        @app.route("/defaults")
        async def h():
            return "ok"

        registry = RouteRegistry()
        assert "GET" in registry.all["_"]

    def test_route_lowercase_method_is_uppercased(self):
        import renus.app as app_mod

        app = app_mod.App()

        @app.route("/lower", method="post", middlewares=[])
        async def h():
            return "ok"

        registry = RouteRegistry()
        assert "POST" in registry.all["_"]
        assert "post" not in registry.all["_"]

    def test_route_resolves_through_registry(self):
        import renus.app as app_mod

        app = app_mod.App()

        @app.route("/users/{uid:int}")
        async def get_user():
            return "ok"

        request = _create_mock_request("GET", "_")
        result = RouteRegistry().resolve(request, {"path": "/users/7"})
        assert result is not None
        assert result["func"] is get_user
        assert result["args"] == {"uid": 7}

    def test_run_forward_defaults_to_uvicorn(self):
        import renus.app as app_mod

        app = app_mod.App()
        uvicorn_run = MagicMock()
        with patch.object(
            __import__("uvicorn", fromlist=["run"]), "run", uvicorn_run
        ):
            app.run("main:app", host="127.0.0.1", port=4000, reload=True, ws_max_size=1)
            uvicorn_run.assert_called_once_with(
                "main:app",
                host="127.0.0.1",
                port=4000,
                reload=True,
                ws_max_size=1,
            )

    def test_run_defaults_app_to_self(self):
        import renus.app as app_mod

        app = app_mod.App()
        uvicorn_run = MagicMock()
        with patch.object(
            __import__("uvicorn", fromlist=["run"]), "run", uvicorn_run
        ):
            app.run(host="127.0.0.1", port=8000)
            uvicorn_run.assert_called_once_with(
                app, host="127.0.0.1", port=8000, reload=False
            )

class TestMiddlewareChain:

    @pytest.mark.asyncio
    async def test_onion_middleware_runs_before_and_after(self):
        from renus.router import is_onion_middleware, run_middleware_chain

        order = []

        async def auth(request, method, res):
            order.append("before")
            resp = await method(**res["args"])
            order.append("after")
            return resp

        async def handler(**kwargs):
            order.append("handler")
            return "ok"

        assert is_onion_middleware(auth)
        result = await run_middleware_chain(request=None, middlewares=[auth], res={"args": {}}, endpoint=handler)
        assert result == "ok"
        assert order == ["before", "handler", "after"]

    @pytest.mark.asyncio
    async def test_multiple_onion_middlewares_nest(self):
        from renus.router import run_middleware_chain

        log = []

        async def outer(request, method, res):
            log.append("outer-before")
            resp = await method(**res["args"])
            log.append("outer-after")
            return resp

        async def inner(request, method, res):
            log.append("inner-before")
            resp = await method(**res["args"])
            log.append("inner-after")
            return resp

        async def handler(**kwargs):
            log.append("handler")
            return "done"

        await run_middleware_chain(None, [outer, inner], {"args": {}}, handler)
        assert log == ["outer-before", "inner-before", "handler", "inner-after", "outer-after"]

    @pytest.mark.asyncio
    async def test_middleware_can_short_circuit_before_handler(self):
        from renus.router import is_onion_middleware, run_middleware_chain

        called = []

        async def deny(request, method, res):
            return "denied"

        async def handler(**kwargs):
            called.append("handler")
            return "ok"

        assert is_onion_middleware(deny)
        result = await run_middleware_chain(None, [deny], {"args": {}}, handler)
        assert result == "denied"
        assert called == []

    @pytest.mark.asyncio
    async def test_onion_middleware_can_rewrite_args(self):
        from renus.router import run_middleware_chain

        async def set_arg(request, method, res):
            res["args"]["who"] = "world"
            return await method(**res["args"])

        async def handler(**kwargs):
            return f"hello {kwargs['who']}"

        result = await run_middleware_chain(None, [set_arg], {"args": {}}, handler)
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_legacy_middleware_still_short_circuits(self):
        from renus.router import run_middleware_chain

        calls = []

        async def legacy(request):
            calls.append("gate")
            return True

        async def blocker(request):
            return "blocked"

        async def handler(**kwargs):
            calls.append("handler")
            return "ok"

        middleware = Middleware(None, middlewares=[legacy, blocker])
        assert await middleware.next() == "blocked"
        calls.clear()

        result = await run_middleware_chain(None, [legacy], {"args": {}}, handler)
        assert result == "ok"
        assert calls == ["gate", "handler"]

    @pytest.mark.asyncio
    async def test_mixed_legacy_and_onion_chain(self):
        from renus.router import run_middleware_chain

        log = []

        async def gate(request):
            log.append("gate")
            return True

        async def onion(request, method, res):
            log.append("onion-before")
            resp = await method(**res["args"])
            log.append("onion-after")
            return resp

        async def handler(**kwargs):
            log.append("handler")
            return "done"

        result = await run_middleware_chain(None, [gate, onion], {"args": {}}, handler)
        assert result == "done"
        assert log == ["gate", "onion-before", "handler", "onion-after"]
