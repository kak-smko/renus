from __future__ import annotations

class ClientDisconnect(Exception):
    """Raised when the client disconnects before the request completes."""
    pass
