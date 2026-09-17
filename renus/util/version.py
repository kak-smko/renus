"""Version helpers for the Renus package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version

import renus

_DEFAULT_VERSION = "3.0.0"


def get_version() -> str:
    """Return the current Renus version from the package or installed metadata."""
    package_value = getattr(renus, "__version__", None)
    if package_value:
        return str(package_value)

    try:
        return package_version("renus")
    except PackageNotFoundError:
        return _DEFAULT_VERSION
