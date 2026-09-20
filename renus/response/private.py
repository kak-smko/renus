from __future__ import annotations

from typing import Any

from renus.cache import Cache
from renus.response.base import Response
from renus.response.status import Status
from renus.util.random import get_random_string

class PrivateResponse(Response):
    """Response pointing to a privately stored, tokenized URL."""

    media_type = "text/plain"

    def __init__(
        self,
        url: str,
        status_code: Status = Status.HTTP_200_OK,
        headers: Any = None,
        background: Any = None,
    ) -> None:
        """Initialize a private response.

        Parameters
        ----------
        url:
            URL to serve as the response body.
        status_code:
            HTTP status code for the response.
        headers:
            Optional mapping of initial response headers.
        background:
            Optional task to run after the response is sent.
        """
        super().__init__(
            content=url, status_code=status_code, headers=headers, background=background
        )

    def render(self, content: Any) -> bytes:
        """Render a tokenized private URL for ``content``."""
        if content is None:
            return b""
        rnd = get_random_string(50)
        Cache().put(rnd, "access to private")
        content = f"/storage/private/{rnd}/{content}"
        return content.encode(self.charset)

