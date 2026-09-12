from __future__ import annotations

from urllib.parse import unquote

def parse_options_header(value: str | bytes | None) -> tuple[str, dict[str, str]]:
    """Parse a header value into its main value and semicolon-separated options.

    Parameters
    ----------
    value:
        Raw header value. ``None`` or empty input yields an empty result.
    """
    if value is None:
        return "", {}
    if isinstance(value, bytes):
        value = value.decode("latin-1")

    value = value.strip()
    if not value:
        return "", {}

    segments = _split_unquoted_semicolons(value)
    header_value = segments[0].strip().strip('"')

    options: dict[str, str] = {}
    for segment in segments[1:]:
        index = segment.find("=")
        if index == -1:
            continue
        key = segment[:index].strip().strip('"')
        raw = segment[index + 1 :].strip()
        if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        if key:
            options[key] = unquote(raw)

    return header_value, options

def _split_unquoted_semicolons(value: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    in_quotes = False
    escaped = False

    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char == ";" and not in_quotes:
            segments.append("".join(current))
            current = []
        else:
            current.append(char)

    segments.append("".join(current))
    return segments

__all__ = ["parse_options_header"]
