from __future__ import annotations

def full_path_builder(app_prefix: str, path: str) -> str:
    """Join an app prefix and route path into a full path.

    Parameters
    ----------
    app_prefix:
        The application's path prefix.
    path:
        The route path to append.
    """
    parts = [p.strip("/") for p in (app_prefix, path) if p.strip("/")]
    return "/" + "/".join(parts) if parts else "/"

def is_safe_path(path: str) -> bool:
    """Return whether a path avoids traversal outside its root."""
    if "\0" in path:
        return False
    if ".." not in path:
        return True
    for segment in path.split("/"):
        if segment == "..":
            return False
    return True
