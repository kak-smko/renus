from __future__ import annotations

import typing

from renus.websockets.state import WebSocketState

_SEND_TRANSITIONS = {
    WebSocketState.CONNECTING: {"websocket.accept", "websocket.close"},
    WebSocketState.CONNECTED: {"websocket.send", "websocket.close"},
}
_RECEIVE_TYPES = {"websocket.receive", "websocket.disconnect"}

class WebSocketProtocolError(RuntimeError):
    """Raised when a protocol-level WebSocket operation is invalid."""

    pass

class WebSocketProtocol:

    _scope: dict[str, typing.Any]
    _receive: typing.Callable[..., typing.Awaitable[dict[str, typing.Any]]]
    _send: typing.Callable[[dict[str, typing.Any]], typing.Awaitable[None]]
    client_state: WebSocketState
    application_state: WebSocketState

    @property
    def scope(self) -> dict:
        """The WebSocket connection scope."""
        return self._scope

    @property
    def client_connected(self) -> bool:
        """Whether the client side of the connection is connected."""
        return self.client_state is WebSocketState.CONNECTED

    @property
    def application_connected(self) -> bool:
        """Whether the application side of the connection is connected."""
        return self.application_state is WebSocketState.CONNECTED

    @property
    def connected(self) -> bool:
        """Whether both sides of the connection are connected."""
        return self.client_connected and self.application_connected

    async def receive(self) -> dict:
        """Wait for and return the next inbound message."""
        if self.client_state == WebSocketState.CONNECTING:
            message = await self._receive()
            message_type = message.get("type")
            if message_type != "websocket.connect":
                raise WebSocketProtocolError(
                    f'Expected "websocket.connect", got {message_type!r}.'
                )
            self.client_state = WebSocketState.CONNECTED
            return message

        if self.client_state == WebSocketState.CONNECTED:
            message = await self._receive()
            message_type = message.get("type")
            if message_type not in _RECEIVE_TYPES:
                raise WebSocketProtocolError(
                    f"Unexpected message type {message_type!r} during connection."
                )
            if message_type == "websocket.disconnect":
                self.client_state = WebSocketState.DISCONNECTED
            return message

        raise WebSocketProtocolError(
            'Cannot call "receive" once a disconnect message has been received.'
        )

    async def send(self, message: dict) -> None:
        """Send the given message, validating the current state."""
        if self.application_state == WebSocketState.DISCONNECTED:
            raise WebSocketProtocolError(
                'Cannot call "send" once a close message has been sent.'
            )

        message_type = message.get("type")
        allowed = _SEND_TRANSITIONS[self.application_state]
        if message_type not in allowed:
            msg = "Cannot send message type %r in state %s." % (
                message_type,
                self.application_state.name,
            )
            raise WebSocketProtocolError(msg)
        if message_type == "websocket.accept":
            self.application_state = WebSocketState.CONNECTED
        elif message_type == "websocket.close":
            self.application_state = WebSocketState.DISCONNECTED
        await self._send(message)

__all__ = ["WebSocketProtocol", "WebSocketProtocolError"]
