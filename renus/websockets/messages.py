from __future__ import annotations

import typing

from renus.util.codec import json_encode

def accept_message(subprotocol: str | None = None) -> dict:
    """Build an ``accept`` message for the given subprotocol."""
    message: dict = {"type": "websocket.accept"}
    if subprotocol is not None:
        message["subprotocol"] = subprotocol
    return message

def send_text_message(data: str) -> dict:
    """Build a text ``send`` message with the given data."""
    return {"type": "websocket.send", "text": data}

def send_bytes_message(data: bytes) -> dict:
    """Build a binary ``send`` message with the given data."""
    return {"type": "websocket.send", "bytes": data}

def send_json_message(data: typing.Any, mode: str = "text") -> dict:
    """Build a ``send`` message from JSON data, encoded as text or binary."""
    if mode not in ("text", "binary"):
        raise ValueError("mode must be 'text' or 'binary'")
    text = json_encode(data)
    if mode == "text":
        return {"type": "websocket.send", "text": text}
    return {"type": "websocket.send", "bytes": text.encode("utf-8")}

def close_message(code: int = 1000) -> dict:
    """Build a ``close`` message with the given status code."""
    return {"type": "websocket.close", "code": code}

__all__ = [
    "accept_message",
    "close_message",
    "send_text_message",
    "send_bytes_message",
    "send_json_message",
]
