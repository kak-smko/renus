from __future__ import annotations

import typing

from renus.request import Injection, Request
from renus.websockets.messages import (
    accept_message,
    close_message,
    send_bytes_message,
    send_json_message,
    send_text_message,
)
from renus.websockets.protocol import WebSocketProtocol, WebSocketProtocolError
from renus.util.codec import json_decode
from renus.websockets.state import WebSocketDisconnect, WebSocketState

class WebSocket(Request, WebSocketProtocol):

    def __init__(self, scope, receive, send) -> None:
        """Initialize a WebSocket connection over the given scope and channels.

        Parameters
        ----------
        scope:
            The ASGI ``websocket`` connection scope.
        receive:
            Awaitable callable returning the next inbound message.
        send:
            Awaitable callable that sends an outbound message.
        """
        super().__init__(scope, receive)
        if scope.get("type") != "websocket":
            raise WebSocketProtocolError(
                f"Expected scope type 'websocket', got {scope.get('type')!r}."
            )
        self._scope = scope
        self._receive = receive
        self._send = send
        self.client_state = WebSocketState.CONNECTING
        self.application_state = WebSocketState.CONNECTING

    @property
    def requested_subprotocols(self) -> typing.List[str]:
        """The subprotocols offered by the client."""
        offered: typing.List[str] = []
        for name, value in self._scope.get("headers", []):
            if name.lower() == b"sec-websocket-protocol":
                offered.extend(
                    part.strip() for part in value.decode("latin-1").split(",")
                )
        return offered

    async def accept(self, subprotocol: str | None = None) -> None:
        """Accept the connection, optionally selecting a subprotocol."""
        if subprotocol is not None and subprotocol not in self.requested_subprotocols:
            raise WebSocketProtocolError(
                f"Subprotocol {subprotocol!r} was not offered by the client."
            )
        if self.client_state == WebSocketState.CONNECTING:

            await self.receive()
        await self.send(accept_message(subprotocol))

    def _raise_on_disconnect(self, message) -> None:
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message["code"])

    async def receive_text(self, protect: bool = True) -> str:
        """Receive and return the next message as text."""
        message = await self.receive()
        self._raise_on_disconnect(message)
        return Injection().protect(message["text"]) if protect else message["text"]

    async def receive_bytes(self) -> bytes:
        """Receive and return the next message as raw bytes."""
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["bytes"]

    async def receive_json(self, protect: bool = True) -> typing.Any:
        """Receive and decode the next message as JSON."""
        message = await self.receive()
        self._raise_on_disconnect(message)
        if "text" in message:
            text = message["text"]
        else:
            text = message["bytes"].decode("utf-8")
        return Injection().protect(json_decode(text)) if protect else json_decode(text)

    async def iter_messages(self) -> typing.AsyncIterator[dict]:
        """Yield inbound messages until the client disconnects."""
        try:
            while True:
                message = await self.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message["code"])
                yield message
        except WebSocketDisconnect:
            pass

    def __aiter__(self) -> typing.AsyncIterator[dict]:
        """Iterate over inbound messages."""
        return self.iter_messages()

    async def iter_text(self) -> typing.AsyncIterator[str]:
        """Yield inbound messages decoded as text."""
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            pass

    async def iter_bytes(self) -> typing.AsyncIterator[bytes]:
        """Yield inbound messages as raw bytes."""
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            pass

    async def iter_json(self) -> typing.AsyncIterator[typing.Any]:
        """Yield inbound messages decoded as JSON."""
        try:
            while True:
                yield await self.receive_json()
        except WebSocketDisconnect:
            pass

    async def send_text(self, data: str) -> None:
        """Send a text message."""
        await self.send(send_text_message(data))

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary message."""
        await self.send(send_bytes_message(data))

    async def send_json(self, data: typing.Any, mode: str = "text") -> None:
        """Send JSON data, encoded as text or binary."""
        await self.send(send_json_message(data, mode))

    async def close(self, code: int = 1000) -> None:
        """Close the connection with the given status code."""
        try:
            await self.send(close_message(code))
        except WebSocketProtocolError:

            pass

__all__ = ["WebSocket"]
