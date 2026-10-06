from __future__ import annotations

from typing import Any
from renus.response.base import Response
from renus.util import dumps_bytes

class JsonResponse(Response):
    """JSON-encoded response."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        """Serialize ``content`` to JSON bytes."""
        if isinstance(content, bytes):
            return content
        return dumps_bytes(content)
