from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import quote_plus

from renus.datastructures import Background
from renus.response.base import Response
from renus.response.status import Status
from renus.util import dumps_bytes

class JsonResponse(Response):
    """JSON-encoded response."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        """Serialize ``content`` to JSON bytes."""
        if isinstance(content, bytes):
            return content
        return dumps_bytes(content)

class JsonResponseRedirect(Response):
    """JSON response carrying a redirect location payload."""

    def __init__(
        self,
        content: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        background: Optional[Background] = None,
        cryptor: Optional[Any] = None,
    ) -> None:
        """Initialize a JSON redirect response.

        Parameters
        ----------
        content:
            Redirect URL to encode as the ``location`` value.
        headers:
            Optional mapping of initial response headers.
        background:
            Optional task to run after the response is sent.
        cryptor:
            Optional callable used to encrypt the response body.
        """
        super().__init__(
            content,
            Status.HTTP_307_TEMPORARY_REDIRECT,
            headers,
            "application/json",
            background,
            cryptor,
        )

    def render(self, url: str) -> bytes:
        """Encode the redirect ``url`` into a JSON body."""
        content = {"location": quote_plus(url, safe="://%#?&=@[]!$&'()*+,;")}
        return dumps_bytes(content)

