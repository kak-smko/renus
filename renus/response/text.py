from __future__ import annotations

from typing import Any

from renus.response.base import Response

class HtmlResponse(Response):
    """HTML-encoded response."""

    media_type = "text/html"

class TextResponse(Response):
    """Plain-text response."""

    media_type = "text/plain"

    def render(self, content: Any) -> bytes:
        """Convert ``content`` to text bytes."""
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return str(content).encode(self.charset)

__all__ = ["HtmlResponse", "TextResponse"]
