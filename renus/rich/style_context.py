"""Shared style lookup context for rich rendering helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_styles: Mapping[str, Any] = {}


def configure_styles(styles: Mapping[str, Any]) -> None:
    """Configure the named terminal styles used by helper objects."""
    global _styles
    _styles = styles


def lookup_style(name: str) -> Any:
    """Return a configured style by name."""
    return _styles.get(name)
