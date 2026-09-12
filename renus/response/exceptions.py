from __future__ import annotations

import traceback
from typing import Any

from renus.log import Log

from renus.response.status import Status
from renus.util.codec import json_encode

class FileResponseError(RuntimeError):
    """Raised when a file response cannot be served."""

class HTTPException(RuntimeError):
    """Raised to signal an HTTP error response."""

    def __init__(
        self,
        detail: Any = None,
        status_code: Status = Status.HTTP_400_BAD_REQUEST,
    ) -> None:
        """Initialize the exception.

        Parameters
        ----------
        detail:
            Error detail; a string is wrapped as ``{"msg": detail}``.
        status_code:
            HTTP status code associated with the error.
        """
        if isinstance(detail, str):
            detail = {"msg": detail}
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail, status_code)

def abort(
    msg: Any, status_code: Status = Status.HTTP_400_BAD_REQUEST
) -> None:
    """Raise an ``HTTPException`` with the given message and status."""
    raise HTTPException(msg, status_code)

def abort_if(
    condition: bool,
    msg: Any,
    status_code: Status = Status.HTTP_400_BAD_REQUEST,
) -> None:
    """Raise an ``HTTPException`` when ``condition`` is true."""
    if condition:
        raise HTTPException(msg, status_code)

def abort_unless(
    condition: bool,
    msg: Any,
    status_code: Status = Status.HTTP_400_BAD_REQUEST,
) -> None:
    """Raise an ``HTTPException`` when ``condition`` is false."""
    if not condition:
        raise HTTPException(msg, status_code)

def debug_response(exc: Exception, debug: bool = False):
    """Return a response payload for the given exception."""
    if (isinstance(exc, RuntimeError)
            and isinstance(exc.args[0], dict)
            and len(exc.args) == 2 and "msg" in exc.args[0]):
        return exc.args[0], exc.args[1]

    status_code = Status.HTTP_500_INTERNAL_SERVER_ERROR
    traceback_obj = traceback.TracebackException.from_exception(
        exc, capture_locals=True
    )

    error = f"{traceback_obj.exc_type.__name__}: {str(traceback_obj)}"
    stacks = traceback_obj.stack.format()
    stack_list = [stack.split("\n") for stack in stacks]

    res = {
        "msg": error,
        "file": traceback.format_tb(exc.__traceback__),
        "stack": stack_list,
    }
    Log().error(json_encode(res, indent=True))
    if not debug:
        return {"msg": "Internal Server Error"}, status_code
    traceback.print_tb(exc.__traceback__)
    return res, status_code

__all__ = [
    "HTTPException",
    "FileResponseError",
    "abort",
    "abort_if",
    "abort_unless",
    "debug_response",
]
