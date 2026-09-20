from __future__ import annotations

from typing import Mapping, Optional
from urllib.parse import quote_plus

from renus.datastructures import Background
from renus.response.base import Response
from renus.response.status import Status

class RedirectResponse(Response):
    """Redirect the client to another URL."""

    def __init__(
        self,
        url: str,
        status_code: Status = Status.HTTP_307_TEMPORARY_REDIRECT,
        headers: Optional[Mapping[str, str]] = None,
        background: Optional[Background] = None,
    ) -> None:
        """Initialize a redirect response.

        Parameters
        ----------
        url:
            Target URL for the ``Location`` header.
        status_code:
            HTTP redirect status code.
        headers:
            Optional mapping of initial response headers.
        background:
            Optional task to run after the response is sent.
        """
        headers = {} if headers is None else dict(headers)
        headers["location"] = quote_plus(url, safe=":/%#?&=@[]!$&'()*+,;")
        super().__init__(
            content=b"",
            status_code=status_code,
            headers=headers,
            background=background,
        )

