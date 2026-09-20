from typing import List

import pytest

from renus.websockets import (
    WebSocket,
    WebSocketCloseCode,
    WebSocketDisconnect,
    WebSocketState,
    WebSocketProtocolError,
    accept_message,
    close_message,
    send_bytes_message,
    send_json_message,
    send_text_message,
)

def _scope(subprotocols: bool = False) -> dict:
    headers = [(b"host", b"example.com"), (b"origin", b"http://example.com")]
    if subprotocols:
        headers.append((b"sec-websocket-protocol", b"chat, superchat"))
    return {
        "type": "websocket",
        "scheme": "ws",
        "path": "/ws",
        "query_string": b"",
        "headers": headers,
    }

def _make_ws(protocol: List[dict], sent: List[dict], subprotocols: bool = False):
    scope = _scope(subprotocols)
    queue = list(protocol)

    async def receive():
        return queue.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    ws = WebSocket(scope, receive, send)
    return ws

@pytest.fixture(autouse=True)
def _reset_singletons():
    yield

class TestState:

    def test_state_ordering(self):
        assert WebSocketState.CONNECTING.value < WebSocketState.CONNECTED.value
        assert WebSocketState.CONNECTED.value < WebSocketState.DISCONNECTED.value

    def test_disconnect_carries_code(self):
        exc = WebSocketDisconnect(1006)
        assert exc.code == 1006
        assert "1006" in str(exc)

    def test_disconnect_reason(self):
        exc = WebSocketDisconnect(1000, reason="done")
        assert exc.reason == "done"
        assert "done" in str(exc)

    def test_close_code_values(self):
        assert WebSocketCloseCode.NORMAL == 1000
        assert WebSocketCloseCode.POLICY_VIOLATION == 1008

class TestProtocolTransitions:

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        sent: List[dict] = []
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "hi"},
                {"type": "websocket.disconnect", "code": 1000},
            ],
            sent,
        )
        assert ws.client_state is WebSocketState.CONNECTING

        await ws.receive()
        assert ws.client_state is WebSocketState.CONNECTED

        msg = await ws.receive()
        assert msg["text"] == "hi"

        msg = await ws.receive()
        assert msg["type"] == "websocket.disconnect"
        assert ws.client_state is WebSocketState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_receive_after_disconnect_raises(self):
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
    async def test_unexpected_first_message_raises(self):
        ws = _make_ws([{"type": "websocket.receive", "text": "nope"}], [])
        with pytest.raises(WebSocketProtocolError):
            await ws.receive()

    @pytest.mark.asyncio
    async def test_send_after_close_raises(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        await ws.send(accept_message())
        await ws.send(close_message())
        with pytest.raises(WebSocketProtocolError):
            await ws.send(send_text_message("late"))

    @pytest.mark.asyncio
    async def test_invalid_send_type_raises(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        with pytest.raises(WebSocketProtocolError):
            await ws.send({"type": "websocket.send", "text": "x"})

    @pytest.mark.asyncio
    async def test_connection_properties(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        assert ws.client_connected is False
        assert ws.application_connected is False
        await ws.accept()
        assert ws.application_connected is True
        assert ws.connected is True

class TestSessionAPI:

    @pytest.mark.asyncio
    async def test_accept_and_send_json(self):
        sent: List[dict] = []
        ws = _make_ws([{"type": "websocket.connect"}], sent, subprotocols=True)
        await ws.accept("chat")
        assert sent == [{"type": "websocket.accept", "subprotocol": "chat"}]
        assert ws.application_state is WebSocketState.CONNECTED

        await ws.send_json({"ok": True})
        encoded = sent[-1]
        assert encoded["type"] == "websocket.send"
        assert "ok" in encoded["text"]

    @pytest.mark.asyncio
    async def test_send_json_binary_mode(self):
        sent: List[dict] = []
        ws = _make_ws([{"type": "websocket.connect"}], sent)
        await ws.accept()
        await ws.send_json({"n": 1}, mode="binary")
        assert sent[-1]["type"] == "websocket.send"
        assert b"1" in sent[-1]["bytes"]

    @pytest.mark.asyncio
    async def test_receive_text(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "hello"},
            ],
            [],
        )
        await ws.accept()
        assert await ws.receive_text(protect=False) == "hello"

    @pytest.mark.asyncio
    async def test_receive_json_bytes(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "bytes": b'{"a":1}'},
            ],
            [],
        )
        await ws.accept()
        assert await ws.receive_json(protect=False) == {"a": 1}

    @pytest.mark.asyncio
    async def test_receive_disconnect_raises(self):
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
    async def test_iter_text_stops_on_disconnect(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "a"},
                {"type": "websocket.receive", "text": "b"},
                {"type": "websocket.disconnect", "code": 1000},
            ],
            [],
        )
        await ws.accept()
        assert [t async for t in ws.iter_text()] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_aiter_yields_messages(self):
        ws = _make_ws(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "x"},
                {"type": "websocket.disconnect", "code": 1000},
            ],
            [],
        )
        await ws.accept()
        messages = [m async for m in ws]
        assert [m["text"] for m in messages if "text" in m] == ["x"]

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self):
        sent: List[dict] = []
        ws = _make_ws([{"type": "websocket.connect"}], sent)
        await ws.accept()
        await ws.close(WebSocketCloseCode.NORMAL.value)
        await ws.close(WebSocketCloseCode.NORMAL.value)
        assert sent[-1] == {"type": "websocket.close", "code": 1000}

    @pytest.mark.asyncio
    async def test_requested_subprotocols(self):
        ws = _make_ws([{"type": "websocket.connect"}], [], subprotocols=True)
        assert ws.requested_subprotocols == ["chat", "superchat"]

    @pytest.mark.asyncio
    async def test_accept_unoffered_subprotocol_raises(self):
        ws = _make_ws([{"type": "websocket.connect"}], [])
        with pytest.raises(WebSocketProtocolError):
            await ws.accept("graphql")

    def test_wrong_scope_type_raises(self):
        with pytest.raises(WebSocketProtocolError):
            WebSocket({"type": "http"}, None, None)

class TestMessageBuilders:

    def test_accept_without_subprotocol(self):
        assert accept_message() == {"type": "websocket.accept"}

    def test_accept_with_subprotocol(self):
        assert accept_message("chat") == {"type": "websocket.accept", "subprotocol": "chat"}

    def test_text_bytes_close(self):
        assert send_text_message("hi") == {"type": "websocket.send", "text": "hi"}
        assert send_bytes_message(b"\x00\x01") == {"type": "websocket.send", "bytes": b"\x00\x01"}
        assert close_message() == {"type": "websocket.close", "code": 1000}

    def test_send_json_invalid_mode(self):
        with pytest.raises(ValueError):
            send_json_message({}, mode="base64")

    def test_send_json_uses_json_encoder_timestamp(self):
        import datetime

        msg = send_json_message({"at": datetime.datetime(2020, 1, 1)})
        assert '2020-01-01' in msg["text"]

    def test_close_message_custom_code(self):
        assert close_message(1008) == {"type": "websocket.close", "code": 1008}
