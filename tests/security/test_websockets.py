"""Security regression tests for :mod:`renus.websockets`.

These tests document the security-relevant behavior of the WebSocket layer:

- received text/JSON messages must be XSS-sanitized by default, and the raw
  path must be an explicit ``protect=False`` opt-out,
- JSON decoding of attacker-controlled frames must fail loudly instead of
  silently returning garbage,
- the subprotocol handshake must never echo subprotocols the client did not
  offer, and must never reflect control characters into the 101 response,
- the ASGI state machine must reject out-of-order messages so data cannot be
  sent or accepted outside a completed handshake,
- close/reject paths must be idempotent and fail closed.
"""

from __future__ import annotations

import pytest

from renus.websockets import (
    WebSocket,
    WebSocketCloseCode,
    WebSocketDisconnect,
    WebSocketProtocolError,
    WebSocketState,
    accept_message,
    close_message,
    send_text_message,
)


# --------------------------------------------------------------------------
# Helpers (mirror tests/test_websockets.py)
# --------------------------------------------------------------------------


def _scope(extra_headers: list | None = None) -> dict:
    headers = [(b"host", b"example.com"), (b"origin", b"http://example.com")]
    headers.extend(extra_headers or [])
    return {
        "type": "websocket",
        "scheme": "ws",
        "path": "/ws",
        "query_string": b"",
        "headers": headers,
    }


def _make_ws(inbound: list, sent: list, extra_headers: list | None = None):
    queue = list(inbound)

    async def receive():
        return queue.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    return WebSocket(_scope(extra_headers), receive, send)


@pytest.fixture(autouse=True)
def _reset_singletons():
    yield


# --------------------------------------------------------------------------
# receive_text: default-on XSS sanitization
# --------------------------------------------------------------------------


class TestWebSocketTextSanitization:

    @pytest.mark.asyncio
    async def test_script_tag_neutralized_by_default(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "<script>alert(1)</script>"},
            ],
            [],
        )
        await ws.accept()
        out = await ws.receive_text()
        assert "<script" not in out
        assert "alert(1)" in out  # payload kept inert as display text

    @pytest.mark.asyncio
    async def test_tag_blocking_is_case_insensitive(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "<ScRiPt>x</ScRiPt>"},
            ],
            [],
        )
        await ws.accept()
        out = await ws.receive_text()
        # The tag is rewritten to its plural block name and escaped, so it
        # can never appear as a live tag in any casing.
        assert "<script" not in out.lower()
        assert "&lt;scripts&gt;" in out

    @pytest.mark.asyncio
    async def test_event_handler_neutralized(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": '<img src=x onerror="alert(1)">'},
            ],
            [],
        )
        await ws.accept()
        out = await ws.receive_text()
        assert "onerror" not in out

    @pytest.mark.asyncio
    async def test_javascript_url_neutralized(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": '<a href="javascript:alert(1)">x</a>'},
            ],
            [],
        )
        await ws.accept()
        out = await ws.receive_text()
        # The scheme is pinned to http://, so it cannot execute as javascript:.
        assert 'href="javascript:' not in out
        assert "http://javascript:" in out

    @pytest.mark.asyncio
    async def test_double_encoded_entity_blocked(self):
        # Injection escapes after unescaping, so entity-encoded tags are
        # parsed as real tags and blocked like their literal form.
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {
                    "type": "websocket.receive",
                    "text": "&lt;script&gt;alert(1)&lt;/script&gt;",
                },
            ],
            [],
        )
        await ws.accept()
        out = await ws.receive_text()
        assert "<script" not in out

    @pytest.mark.asyncio
    async def test_protection_is_on_without_argument(self):
        # Calling receive_text() with no arguments must sanitize; an app that
        # forgets the parameter is still protected by default.
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "<b>bold</b>"},
            ],
            [],
        )
        await ws.accept()
        out = await ws.receive_text()
        assert "<b>" not in out
        assert "&lt;b&gt;" in out

    @pytest.mark.asyncio
    async def test_protect_false_is_explicit_opt_out(self):
        # Raw passthrough only happens when the application explicitly opts
        # out; the raw value must round-trip unchanged (no partial rewrite).
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "<b>bold</b>"},
            ],
            [],
        )
        await ws.accept()
        assert await ws.receive_text(protect=False) == "<b>bold</b>"


# --------------------------------------------------------------------------
# receive_json: sanitization and safe decoding of attacker-controlled frames
# --------------------------------------------------------------------------


class TestWebSocketJsonSanitization:

    @pytest.mark.asyncio
    async def test_nested_values_sanitized(self):
        payload = '{"a": ["<script>x</script>", {"b": "<img src=x onerror=y>"}]}'
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": payload},
            ],
            [],
        )
        await ws.accept()
        data = await ws.receive_json()
        assert "<script" not in data["a"][0]
        assert "onerror" not in data["a"][1]["b"]

    @pytest.mark.asyncio
    async def test_dict_keys_escaped(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": '{"<b>": "x"}'},
            ],
            [],
        )
        await ws.accept()
        data = await ws.receive_json()
        (key, _) = next(iter(data.items()))
        assert "<b>" not in key

    @pytest.mark.asyncio
    async def test_binary_json_sanitized(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "bytes": b'{"m": "<script>x</script>"}'},
            ],
            [],
        )
        await ws.accept()
        data = await ws.receive_json()
        assert "<script" not in data["m"]

    @pytest.mark.asyncio
    async def test_primitives_pass_through_unmodified(self):
        for raw, expected in (
            ('{"n": 3}', 3),
            ('{"flag": true}', True),
            ('{"nothing": null}', None),
        ):
            ws = _make_ws(
                [
                    {"type": "websocket.connect"},
                    {"type": "websocket.receive", "text": raw},
                ],
                [],
            )
            await ws.accept()
            data = await ws.receive_json()
            (value,) = data.values()
            assert value is expected or value == expected

    @pytest.mark.asyncio
    async def test_safe_markup_kept_inert_not_dropped(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": '{"m": "a & b <tag>"}'},
            ],
            [],
        )
        await ws.accept()
        data = await ws.receive_json()
        assert "a & b" in data["m"]
        assert "<tag>" not in data["m"]

    @pytest.mark.asyncio
    async def test_invalid_json_fails_loudly(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "{not json"},
            ],
            [],
        )
        await ws.accept()
        with pytest.raises(ValueError):
            await ws.receive_json()

    @pytest.mark.asyncio
    async def test_invalid_utf8_json_fails_loudly(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "bytes": b'{"a": "\xff\xfe"}'},
            ],
            [],
        )
        await ws.accept()
        with pytest.raises(UnicodeDecodeError):
            await ws.receive_json()

    @pytest.mark.asyncio
    async def test_json_is_data_not_code(self):
        # A JSON string carrying markup is sanitized as text; decoding must
        # never evaluate, import, or construct anything executable.
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {
                    "type": "websocket.receive",
                    "text": '{"m": "__import__(\'os\').system(\'id\')"}',
                },
            ],
            [],
        )
        await ws.accept()
        data = await ws.receive_json()
        assert "__import__" in data["m"]  # preserved as inert display text


# --------------------------------------------------------------------------
# Subprotocol negotiation: no reflection of unoffered or hostile values
# --------------------------------------------------------------------------


class TestSubprotocolNegotiation:

    @pytest.mark.asyncio
    async def test_accept_rejects_unoffered_subprotocol(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        with pytest.raises(WebSocketProtocolError):
            await ws.accept("chat")

    @pytest.mark.asyncio
    async def test_subprotocol_match_is_exact(self):
        # Matching is case-sensitive: a near-miss name is still "unoffered".
        ws = _make_ws(
            [{"type": "websocket.connect"}],
            [],
            extra_headers=[(b"sec-websocket-protocol", b"chat")],
        )
        with pytest.raises(WebSocketProtocolError):
            await ws.accept("CHAT")

    @pytest.mark.asyncio
    async def test_accept_only_echoes_offered_value(self):
        sent: list = []
        ws = _make_ws(
            [{"type": "websocket.connect"}],
            sent,
            extra_headers=[(b"sec-websocket-protocol", b"chat, superchat")],
        )
        await ws.accept("chat")
        assert sent[0] == {"type": "websocket.accept", "subprotocol": "chat"}

    @pytest.mark.asyncio
    async def test_duplicate_protocol_headers_merged(self):
        ws = _make_ws(
            [{"type": "websocket.connect"}],
            [],
            extra_headers=[
                (b"sec-websocket-protocol", b"chat"),
                (b"sec-websocket-protocol", b"superchat"),
            ],
        )
        assert ws.requested_subprotocols == ["chat", "superchat"]

    @pytest.mark.asyncio
    async def test_whitespace_around_subprotocols_trimmed(self):
        ws = _make_ws(
            [{"type": "websocket.connect"}],
            [],
            extra_headers=[(b"sec-websocket-protocol", b"  chat , superchat  ")],
        )
        assert ws.requested_subprotocols == ["chat", "superchat"]

    @pytest.mark.asyncio
    async def test_subprotocol_control_chars_not_echoed(self):
        # A hostile client offers a subprotocol containing CRLF. If an app
        # naively echoes back the client's value (e.g. requested_subprotocols[0]),
        # those bytes land in the 101 handshake headers -> response splitting.
        # The session must refuse to select a subprotocol with control chars.
        sent: list = []
        ws = _make_ws(
            [{"type": "websocket.connect"}],
            sent,
            extra_headers=[(b"sec-websocket-protocol", b"chat\r\nX-Injected: 1")],
        )
        offered = ws.requested_subprotocols
        assert offered == ["chat\r\nX-Injected: 1"]  # raw offer is untrusted input
        with pytest.raises(WebSocketProtocolError):
            await ws.accept(offered[0])
        assert all("\r" not in str(m) for m in sent)
        assert all("\n" not in str(m) for m in sent)

    @pytest.mark.asyncio
    async def test_subprotocol_with_other_control_chars_rejected(self):
        # The token check is not CRLF-specific: null bytes, tabs, spaces and
        # 8-bit junk are all rejected before any membership comparison.
        for hostile in (
            "chat\x00",
            "chat\x1f",
            "chat\t",
            "chat chat2",  # space inside a single token
            "chat\xff",  # latin-1 decoded junk from the header
        ):
            sent: list = []
            ws = _make_ws(
                [{"type": "websocket.connect"}],
                sent,
                extra_headers=[(b"sec-websocket-protocol", hostile.encode("latin-1"))],
            )
            with pytest.raises(WebSocketProtocolError):
                await ws.accept(hostile)
            assert sent == []

    @pytest.mark.asyncio
    async def test_subprotocol_token_punctuation_still_accepted(self):
        # RFC 7230 tchar punctuation stays legal so real subprotocol names
        # like "graphql-ws" or "chat.v2+json" keep working.
        sent: list = []
        ws = _make_ws(
            [{"type": "websocket.connect"}],
            sent,
            extra_headers=[(b"sec-websocket-protocol", b"chat.v2+json, graphql-ws")],
        )
        await ws.accept("chat.v2+json")
        assert sent[0] == {"type": "websocket.accept", "subprotocol": "chat.v2+json"}

    @pytest.mark.asyncio
    async def test_empty_subprotocol_rejected(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        with pytest.raises(WebSocketProtocolError):
            await ws.accept("")


# --------------------------------------------------------------------------
# ASGI state machine abuse: no data outside a completed handshake
# --------------------------------------------------------------------------


class TestProtocolStateAbuse:

    @pytest.mark.asyncio
    async def test_data_before_handshake_rejected(self):
        # An application bug or attacker-triggered early send must not leak
        # frames before the handshake completes.
        ws = _make_ws([{"type": "websocket.connect"}], [])
        with pytest.raises(WebSocketProtocolError):
            await ws.send(send_text_message("early"))

    @pytest.mark.asyncio
    async def test_first_inbound_message_must_be_connect(self):
        ws = _make_ws([{"type": "websocket.receive", "text": "nope"}], [])
        with pytest.raises(WebSocketProtocolError):
            await ws.receive()

    @pytest.mark.asyncio
    async def test_second_connect_message_rejected(self):
        # A replayed handshake must not reset or re-enter CONNECTING state.
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.connect"},
            ],
            [],
        )
        await ws.receive()
        with pytest.raises(WebSocketProtocolError):
            await ws.receive()

    @pytest.mark.asyncio
    async def test_double_accept_rejected(self):
        sent: list = []
        ws = _make_ws([{"type": "websocket.connect"}], sent)
        await ws.accept()
        with pytest.raises(WebSocketProtocolError):
            await ws.accept()
        assert sum(1 for m in sent if m["type"] == "websocket.accept") == 1

    @pytest.mark.asyncio
    async def test_send_after_close_rejected(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        await ws.accept()
        await ws.close()
        with pytest.raises(WebSocketProtocolError):
            await ws.send_text("late")

    @pytest.mark.asyncio
    async def test_receive_after_disconnect_rejected(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.disconnect", "code": 1000},
            ],
            [],
        )
        await ws.receive()
        await ws.receive()
        with pytest.raises(WebSocketProtocolError):
            await ws.receive()

    @pytest.mark.asyncio
    async def test_unknown_message_type_rejected(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.foobar"},
            ],
            [],
        )
        await ws.receive()
        with pytest.raises(WebSocketProtocolError):
            await ws.receive()

    @pytest.mark.asyncio
    async def test_wrong_scope_type_rejected(self):
        # An HTTP scope must never be promoted to a WebSocket session.
        with pytest.raises(WebSocketProtocolError):
            WebSocket({"type": "http"}, None, None)

    @pytest.mark.asyncio
    async def test_iterator_terminates_on_disconnect(self):
        # Iterators must stop at the disconnect frame; an unterminated loop
        # over a dead connection would pin the task forever (DoS).
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.disconnect", "code": 1000},
            ],
            [],
        )
        await ws.accept()
        assert [m async for m in ws] == []


# --------------------------------------------------------------------------
# Close / reject paths: idempotent, fail-closed, no error leakage
# --------------------------------------------------------------------------


class TestCloseAndRejectSafety:

    @pytest.mark.asyncio
    async def test_reject_before_accept_is_supported(self):
        # Rejecting an unauthenticated client with websocket.close is a
        # first-class path and must not require a prior accept.
        sent: list = []
        ws = _make_ws([{"type": "websocket.connect"}], sent)
        await ws.close(WebSocketCloseCode.POLICY_VIOLATION.value)
        assert sent == [{"type": "websocket.close", "code": 1008}]

    @pytest.mark.asyncio
    async def test_close_is_idempotent_and_swallows_protocol_error(self):
        sent: list = []
        ws = _make_ws([{"type": "websocket.connect"}], sent)
        await ws.accept()
        await ws.close()
        await ws.close()  # must not raise
        assert sum(1 for m in sent if m["type"] == "websocket.close") == 1

    @pytest.mark.asyncio
    async def test_state_after_close_is_disconnected(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        await ws.accept()
        await ws.close()
        assert ws.application_state is WebSocketState.DISCONNECTED
        assert ws.application_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_raises_typed_exception_with_code(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.disconnect", "code": 1001},
            ],
            [],
        )
        await ws.accept()
        with pytest.raises(WebSocketDisconnect) as excinfo:
            await ws.receive_text()
        assert excinfo.value.code == 1001

    @pytest.mark.asyncio
    async def test_client_disconnect_does_not_kill_send_side_state_machine(self):
        # A client disconnect moves only the client side; the application
        # side still requires an explicit close before further sends fail.
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.disconnect", "code": 1001},
            ],
            [],
        )
        await ws.accept()
        with pytest.raises(WebSocketDisconnect):
            await ws.receive_text()
        assert ws.client_state is WebSocketState.DISCONNECTED
        assert ws.application_state is WebSocketState.CONNECTED
