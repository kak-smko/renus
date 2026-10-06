"""Security regression tests for :mod:`renus.router`.

These tests document the security-relevant behavior of the routing layer:

- path traversal and null bytes must be rejected before any route matching,
  including traversal that arrives percent-encoded (``..%2f``) or separated
  by backslashes,
- routes must be isolated per method and per subdomain — a mismatch fails
  closed with ``None`` instead of falling back to a wildcard,
- a websocket route must only be resolvable from a real websocket scope,
  not from a plain HTTP request whose method token is literally ``WS``,
- route matching must not collapse or normalize paths in ways that let one
  URL resolve a different route than the one an authorization check saw,
- route registration must fail closed (invalid convertors, duplicate
  parameter names, cyclic includes) instead of producing a broken matcher,
- path parameter convertors must be strict about the alphabet they accept
  and must never yield non-finite values,
- the middleware chain must fail closed: a middleware that does not
  explicitly allow can never fall through to the endpoint,
- matching attacker-controlled paths must complete in bounded time.

"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from renus.router import (
    RouteRegistry,
    Router,
    build_path,
    is_safe_path,
    run_middleware_chain,
)
from renus.router.convertors import FloatConvertor, IDConvertor


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _entry(path: str, name: str = "handler") -> dict:
    return {
        "path": path,
        "controller": None,
        "func": name,
        "middlewares": [],
        "regex": build_path(path),
    }


def _request(subdomain: str = "_", method: str = "GET") -> SimpleNamespace:
    return SimpleNamespace(method=method, subdomain=subdomain)


# ==========================================================================
# A. LIVE VULNERABILITY DEMONSTRATIONS (pass today = the flaw is present)
# ==========================================================================


# ==========================================================================
# B. VERIFIED-SECURE BEHAVIORS (must keep working)
# ==========================================================================

class TestEncodedTraversalRejected:
    """``is_safe_path`` runs on the percent-decoded form as well, so a
    server that does not decode the scope path cannot smuggle ``..%2f..%2f"
    past the safety check into a ``{p:path}`` parameter (uvicorn decodes,
    but the router no longer trusts that). A single decoding pass is
    applied; doubly encoded values such as ``%252e`` stay encoded and
    remain the handler's responsibility."""

    def test_is_safe_path_rejects_encoded_traversal(self):
        assert is_safe_path("/files/..%2f..%2fetc%2fpasswd") is False

    def test_encoded_traversal_rejected_in_resolution(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/files/{p:path}", "files"))

        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(
                _request(), {"method": "GET", "path": "/files/..%2f..%2fetc%2fpasswd"}
            )

    def test_encoded_traversal_rejected_in_fast_resolution(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/files/{p:path}", "files"))

        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve_fast({"method": "GET", "path": "/files/..%2f..%2fetc"})

    def test_encoded_null_byte_is_rejected(self):
        assert is_safe_path("/users%00admin") is False

    def test_doubly_encoded_traversal_is_a_documented_boundary(self):
        # A single decoding pass turns %252e into literal "%2e", which is
        # not traversal. Handlers re-validating decoded values is what
        # covers multi-layer encoding — locked in here so any future
        # change to the decoding depth is a deliberate decision.
        assert is_safe_path("/files/%252e%252e%252fetc") is True


class TestBackslashTraversalRejected:
    """``is_safe_path`` treats backslashes as separators too, so a value
    that a downstream consumer (e.g. a Windows filesystem API) would map
    to ``..`` traversal can no longer be routed."""

    def test_backslash_parent_segment_is_rejected(self):
        assert is_safe_path("/a/..\\secret") is False

    def test_backslash_traversal_rejected_in_resolution(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users/{name}", "show"))

        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(_request(), {"method": "GET", "path": "/users/..\\secret"})


class TestNonFiniteFloatRejected:
    """``{v:float}`` must reject values that overflow to ``inf``: a
    non-finite value can propagate into arithmetic or break JSON encoding
    downstream (orjson refuses to serialize it). Failing with ``ValueError``
    matches the giant-integer behavior of the ``int`` convertor."""

    def test_overflowing_float_raises(self):
        with pytest.raises(ValueError, match="finite"):
            FloatConvertor().convert("9" * 400)

    def test_overflowing_float_rejected_in_resolution(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/rate/{v:float}", "rate"))

        with pytest.raises(ValueError, match="finite"):
            registry.resolve(_request(), {"method": "GET", "path": "/rate/" + "9" * 400})

    def test_finite_floats_still_convert(self):
        assert FloatConvertor().convert("1.5") == 1.5
        # A tiny value underflows to 0.0 instead of raising — fine, it is
        # still finite and safe to hand to a handler.
        assert FloatConvertor().convert("0." + "0" * 400 + "1") == 0.0

        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/rate/{v:float}", "rate"))

        result = registry.resolve(_request(), {"method": "GET", "path": "/rate/2.75"})
        assert result is not None
        assert result["args"]["v"] == 2.75


class TestPathTraversalDefense:
    """Traversal must be rejected unconditionally — before any route lookup,
    in both the normal and the fast resolution path, and even when no route
    is registered at all. Trailing-slash stripping must not create a gap
    (``/users/..`` and ``/users/../`` must both be caught)."""

    @pytest.mark.parametrize(
        "path",
        [
            "/users/../admin",
            "/../etc/passwd",
            "/files/../../secrets",
            "/users/..",
            "/users/../",
            "/..",
            "..",
            "a/../b",
        ],
    )
    def test_resolve_rejects_traversal(self, path):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users", "users"))

        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(_request(), {"method": "GET", "path": path})

    @pytest.mark.parametrize(
        "path", ["/users/../admin", "/users/../../etc", "/a/..", "/.."]
    )
    def test_resolve_fast_rejects_traversal(self, path):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users", "users"))

        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve_fast({"method": "GET", "path": path})

    def test_traversal_rejected_even_with_no_routes_registered(self):
        # The check is unconditional, not a fallback for unmatched paths.
        registry = RouteRegistry()
        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(_request(), {"method": "GET", "path": "/../anything"})

    def test_traversal_towards_a_registered_static_route_is_still_rejected(self):
        # "/users/../admin" must not be normalized to the protected "/admin".
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/admin", "admin_panel"))
        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(_request(), {"method": "GET", "path": "/users/../admin"})

    @pytest.mark.parametrize("path", ["/users\0admin", "/files/a.txt\0.exe", "\0"])
    def test_null_bytes_are_rejected(self, path):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users", "users"))

        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(_request(), {"method": "GET", "path": path})

    def test_null_byte_rejected_in_fast_path(self):
        registry = RouteRegistry()
        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve_fast({"method": "GET", "path": "/users\0/x"})

    def test_decoded_encoded_traversal_is_caught(self):
        # The flip side of the encoded passthrough demo: once the server
        # decodes %2e/%2f, the literal check must catch it.
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/files/{p:path}", "files"))
        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(
                _request(), {"method": "GET", "path": "/files/../../etc/passwd"}
            )

    def test_is_safe_path_core_contract(self):
        assert is_safe_path("/users") is True
        assert is_safe_path("/api/v1/users") is True
        # Only a full segment counts as traversal; embedded dots are fine.
        assert is_safe_path("/....") is True
        assert is_safe_path("/a..b") is True
        assert is_safe_path("/file..name.txt") is True
        # Full ".." segments are rejected anywhere in the path.
        assert is_safe_path("/a/../b") is False
        assert is_safe_path("/..") is False
        assert is_safe_path("..") is False
        # Null bytes are always rejected.
        assert is_safe_path("/users\0") is False


class TestRouteIdentityConfusion:
    """Route matching must not silently rewrite a URL into a different
    route: no collapsing of double slashes, and a protected static route
    must always win over a sibling wildcard regardless of registration
    order (otherwise a dynamic route could shadow an authorization
    boundary)."""

    def test_double_slash_is_not_collapsed(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users/admin", "admin_panel"))

        assert registry.resolve(_request(), {"method": "GET", "path": "/users//admin"}) is None

    def test_multi_segment_path_does_not_match_str_parameter(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users/{name}", "show"))

        assert registry.resolve(_request(), {"method": "GET", "path": "/users/a/b"}) is None

    def test_static_route_wins_when_registered_after_dynamic(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users/{name}", "dynamic"))
        registry.register("_", "GET", _entry("/users/admin", "admin_panel"))

        result = registry.resolve(_request(), {"method": "GET", "path": "/users/admin"})
        assert result is not None
        assert result["func"] == "admin_panel"
        # The wildcard sibling still serves everyone else.
        sibling = registry.resolve(_request(), {"method": "GET", "path": "/users/bob"})
        assert sibling is not None
        assert sibling["func"] == "dynamic"

    def test_static_route_wins_when_registered_before_dynamic(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users/admin", "admin_panel"))
        registry.register("_", "GET", _entry("/users/{name}", "dynamic"))

        result = registry.resolve(_request(), {"method": "GET", "path": "/users/admin"})
        assert result is not None
        assert result["func"] == "admin_panel"

    def test_resolved_args_contain_exactly_the_registered_parameters(self):
        # No attacker-influenced extra keys can reach the endpoint kwargs.
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users/{name}/posts/{post_id:int}", "show"))

        result = registry.resolve(
            _request(), {"method": "GET", "path": "/users/bob/posts/42"}
        )
        assert result is not None
        assert sorted(result["args"].keys()) == ["name", "post_id"]


class TestSubdomainIsolation:
    """Routes registered for a subdomain must be unreachable from any other
    subdomain or from the default host. The lookup fails closed with
    ``None``; the only fallback is subdomain -> default routes, which is the
    documented shared-site behavior."""

    def test_default_host_cannot_reach_subdomain_routes(self):
        registry = RouteRegistry()
        registry.register("admin", "GET", _entry("/panel", "panel"))
        registry.register("_", "GET", _entry("/public", "public"))

        assert registry.resolve(_request("_"), {"method": "GET", "path": "/panel"}) is None

    def test_other_subdomain_cannot_reach_subdomain_routes(self):
        registry = RouteRegistry()
        registry.register("admin", "GET", _entry("/panel", "panel"))
        registry.register("billing", "GET", _entry("/invoices", "invoices"))

        # billing -> admin routes
        assert (
            registry.resolve(_request("billing"), {"method": "GET", "path": "/panel"})
            is None
        )
        # admin -> billing routes
        assert (
            registry.resolve(_request("admin"), {"method": "GET", "path": "/invoices"})
            is None
        )

    def test_unknown_subdomain_without_default_routes_resolves_nothing(self):
        registry = RouteRegistry()
        registry.register("admin", "GET", _entry("/panel", "panel"))

        assert (
            registry.resolve(_request("evil"), {"method": "GET", "path": "/panel"}) is None
        )

    def test_mixed_case_subdomain_registration_fails_closed(self):
        # request.subdomain is normalized to lowercase; a route registered
        # under "Admin" must stay unreachable for every normalized request.
        # (The registry matches the literal key, so only exact-case fake
        # scopes hit it — real Request objects can never produce that.)
        registry = RouteRegistry()
        registry.register("Admin", "GET", _entry("/x", "mixed"))

        assert registry.has_subdomains is True
        assert registry.resolve(_request("admin"), {"method": "GET", "path": "/x"}) is None
        assert registry.resolve(_request("ADMIN"), {"method": "GET", "path": "/x"}) is None
        assert registry.resolve(_request("_"), {"method": "GET", "path": "/x"}) is None


class TestMethodIsolation:
    """A route registered for one method must not serve another, unknown
    methods must not resolve anything, and HTTP traffic must not resolve a
    websocket route by its real method."""

    def test_wrong_method_does_not_resolve(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users", "users"))

        for method in ("POST", "PUT", "DELETE", "OPTIONS", "HEAD", "WS"):
            assert registry.resolve(_request(), {"method": method, "path": "/users"}) is None

    def test_get_cannot_reach_ws_route(self):
        registry = RouteRegistry()
        registry.register("_", "WS", _entry("/echo", "echo_ws"))

        assert registry.resolve(_request(), {"method": "GET", "path": "/echo"}) is None

    def test_lowercase_method_does_not_resolve(self):
        # The framework uppercases scope["method"] before dispatch; a raw
        # lowercase token must not match anything.
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users", "users"))

        assert registry.resolve(_request(), {"method": "get", "path": "/users"}) is None
        assert registry.resolve_fast({"method": "get", "path": "/users"}) is None

    def test_unsupported_arbitrary_method_does_not_resolve(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users", "users"))

        for method in ("TRACE", "CONNECT", "PATCH", "BREW"):
            assert registry.resolve(_request(), {"method": method, "path": "/users"}) is None
            assert registry.resolve_fast({"method": method, "path": "/users"}) is None


class TestRegistrationFailsClosed:
    """A route that cannot be compiled into a correct matcher must raise at
    registration/include time, never produce a matcher that silently
    matches the wrong paths."""

    def test_unknown_convertor_raises_when_router_is_mounted(self):
        router = Router()
        router.get("/x/{a:bogus}")

        with pytest.raises(ValueError, match="Unknown route parameter type"):
            list(router._iter_routes())

    def test_duplicate_parameter_names_raise(self):
        with pytest.raises(Exception, match="redefinition of group name"):
            build_path("/x/{a}/{a}")

    def test_router_subdomain_underscore_rejected(self):
        with pytest.raises(ValueError, match="subdomain"):
            Router(subdomain="_")

    def test_cyclic_include_rejected(self):
        a = Router()
        b = Router()
        a.include(b)

        with pytest.raises(ValueError, match="cycle"):
            b.include(a)

    def test_self_include_rejected(self):
        router = Router()
        with pytest.raises(ValueError, match="cycle"):
            router.include(router)

    def test_include_non_router_rejected(self):
        router = Router()
        with pytest.raises(TypeError, match="Router instance"):
            router.include(lambda: None)


class TestConvertorStrictness:
    """Convertors define exactly which strings can become typed route
    arguments; anything outside the alphabet must fail to match (or fail
    fast on conversion) rather than coerce."""

    def test_bool_convertor_is_case_sensitive(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/flag/{v:bool}", "flag"))

        assert registry.resolve(_request(), {"method": "GET", "path": "/flag/True"}) is None
        assert registry.resolve(_request(), {"method": "GET", "path": "/flag/1"}) is None
        result = registry.resolve(_request(), {"method": "GET", "path": "/flag/true"})
        assert result is not None
        assert result["args"]["v"] is True

    def test_int_convertor_rejects_signs_and_whitespace(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/id/{n:int}", "int"))

        for value in ("-1", "+5", " 1", "1_000", "0x10"):
            assert (
                registry.resolve(_request(), {"method": "GET", "path": f"/id/{value}"})
                is None
            )

    def test_giant_integer_parameter_fails_fast(self):
        # Python's int-str digit limit turns a multi-thousand-digit path
        # segment into an immediate ValueError instead of a hang.
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/id/{n:int}", "int"))

        start = time.perf_counter()
        with pytest.raises(ValueError):
            registry.resolve(_request(), {"method": "GET", "path": "/id/" + "9" * 5000})
        assert time.perf_counter() - start < 1.0

    def test_uuid_convertor_rejects_non_canonical_forms(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/ref/{u:uuid}", "ref"))

        for value in (
            "not-a-uuid",
            "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
            "d9428888-122b-11e1-b85c-00000000000",  # truncated
            "d9428888122b11e1b85c000000000000",  # no dashes
        ):
            assert (
                registry.resolve(_request(), {"method": "GET", "path": f"/ref/{value}"})
                is None
            )

    def test_id_convertor_requires_prefix(self):
        convertor = IDConvertor()
        with pytest.raises(ValueError, match="id:"):
            convertor.convert("abc123")

    def test_string_convertor_never_yields_empty_segment(self):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/users/{name}", "show"))

        # The pattern requires at least one character, so an empty capture
        # can never reach a handler as an empty identity string.
        assert registry.resolve(_request(), {"method": "GET", "path": "/users/"}) is None


class TestMiddlewareChainFailClosed:
    """The chain must treat any middleware outcome that is not an explicit
    allow as a block. A legacy middleware that forgets to ``return True``
    (e.g. falls off the end and returns ``None``) must deny the request, and
    an onion middleware that short-circuits must keep the endpoint from
    ever running."""

    @pytest.mark.asyncio
    async def test_legacy_middleware_returning_none_blocks_endpoint(self):
        calls = []

        async def forgets_return(request):
            if request.blocked:
                return None  # the classic "forgot return True" bug

        async def endpoint(**kwargs):
            calls.append("endpoint")
            return "ENDPOINT"

        blocked = SimpleNamespace(blocked=True)
        result = await run_middleware_chain(blocked, [forgets_return], {"args": {}}, endpoint)

        assert result is None
        assert calls == []

    @pytest.mark.asyncio
    async def test_legacy_middleware_returning_false_blocks_endpoint(self):
        calls = []

        async def deny(request):
            return False

        async def endpoint(**kwargs):
            calls.append("endpoint")
            return "ENDPOINT"

        result = await run_middleware_chain(SimpleNamespace(), [deny], {"args": {}}, endpoint)
        assert result is False
        assert calls == []

    @pytest.mark.asyncio
    async def test_onion_short_circuit_prevents_endpoint_execution(self):
        calls = []

        async def gate(request, method, res):
            return "DENIED"

        async def endpoint(**kwargs):
            calls.append("endpoint")
            return "ENDPOINT"

        result = await run_middleware_chain(SimpleNamespace(), [gate], {"args": {}}, endpoint)

        assert result == "DENIED"
        assert calls == []

    @pytest.mark.asyncio
    async def test_explicit_legacy_allow_still_reaches_endpoint(self):
        async def allow(request):
            return True

        async def endpoint(**kwargs):
            return "ENDPOINT"

        result = await run_middleware_chain(SimpleNamespace(), [allow], {"args": {}}, endpoint)
        assert result == "ENDPOINT"


class TestBoundedMatching:
    """Route matching runs on attacker-controlled paths. The regex shapes
    used by the convertors (``[^/]+``, ``(?:/[^/]+)*``) must not open the
    door to catastrophic backtracking: adversarial inputs against the worst
    pattern shape (a ``{path}`` parameter followed by a literal) must
    resolve or reject in bounded time."""

    @pytest.mark.parametrize(
        "path",
        [
            "/files/" + "a/" * 40000 + "!",  # repetition starve
            "/files/" + "a" * 50000 + "/x",  # long final segment
            "/files/" + "a" * 50000,  # unterminated long segment
            "/files/" + "%2e%2f" * 20000,  # encoded-looking noise
        ],
    )
    def test_adversarial_paths_resolve_or_reject_quickly(self, path):
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/files/{p:path}/edit", "editor"))

        start = time.perf_counter()
        result = registry.resolve(_request(), {"method": "GET", "path": path})
        elapsed = time.perf_counter() - start

        assert result is None  # none of these end in "/edit"
        # A catastrophic regex would need minutes here; the good case is
        # milliseconds. Generous bound keeps the test non-flaky.
        assert elapsed < 5.0

    def test_traversal_check_runs_before_matching_on_huge_paths(self):
        # A huge traversal path must be rejected by the safety check without
        # ever reaching the regex engine.
        registry = RouteRegistry()
        registry.register("_", "GET", _entry("/files/{p:path}/edit", "editor"))

        start = time.perf_counter()
        with pytest.raises(RuntimeError, match="path traversal"):
            registry.resolve(
                _request(), {"method": "GET", "path": "/files/" + "../" * 100000 + "edit"}
            )
        assert time.perf_counter() - start < 1.0
