from __future__ import annotations

import enum

class WebSocketState(enum.Enum):
    """States a WebSocket connection can be in."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2

class WebSocketDisconnect(Exception):
    """Raised when the client disconnects from a WebSocket."""

    def __init__(self, code: int = 1000, reason: str = "") -> None:
        """Initialize with the disconnect code and optional reason."""
        self.code = code
        self.reason = reason
        detail = f" with reason {reason!r}" if reason else ""
        super().__init__(f"WebSocket disconnected with code {code}{detail}")

    def __repr__(self) -> str:
        return f"<WebSocketDisconnect code={self.code}>"

class WebSocketCloseCode(enum.IntEnum):
    """Standard WebSocket close status codes."""

    NORMAL = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    NO_STATUS = 1005
    ABNORMAL = 1006
    INVALID_DATA = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    UNSUPPORTED_EXTENSION = 1010
    INTERNAL_ERROR = 1011
    SERVICE_RESTART = 1012
    TRY_AGAIN_LATER = 1013

__all__ = ["WebSocketState", "WebSocketDisconnect", "WebSocketCloseCode"]
