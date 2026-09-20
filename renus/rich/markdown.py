from __future__ import annotations

import re
from typing import Callable

from ._style import _Style
from .table import Table

_BOLD = _Style(1)
_ITALIC = _Style(3)
_CODE = _Style(36)
_DIM = _Style(2)
_H1 = _Style(1, 4)
_H = _Style(1, 96)
_HR = _Style(90)
_LINK_TEXT = _Style(4)
_LINK_URL = _Style(90)

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")

_HRULE = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$")

_ULIST = re.compile(r"^[-*+]\s+(.+)$")

_OLIST = re.compile(r"^\d+[.)]\s+(.+)$")

_FENCE = re.compile(r"^\s*```\s*$")

def _inline(txt: str) -> str:
    rules: tuple[tuple[str, Callable[[re.Match[str]], str]], ...] = (
        (r"`([^`\n]+)`", lambda m: _CODE(m.group(1))),
        (r"\*\*([^*\n]+)\*\*", lambda m: _BOLD(m.group(1))),
        (r"__([^_\n]+)__", lambda m: _BOLD(m.group(1))),
        (r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda m: _ITALIC(m.group(1))),
        (r"(?<!_)_([^_\n]+)_(?!_)", lambda m: _ITALIC(m.group(1))),
        (r"\[([^\]]+)\]\(([^)]+)\)", _link),
    )
    out = txt
    for regex, styler in rules:
        out = re.sub(regex, styler, out)
    return out

def _link(m: "re.Match[str]") -> str:
    text, url = m.group(1), m.group(2)
    return f"{_LINK_TEXT(text)} ({_LINK_URL(url)})"

class Markdown:
    """Render Markdown text to styled terminal output."""

    @staticmethod
    def render(text: str) -> str:
        """Render the given Markdown ``text`` to styled terminal output."""
        lines = text.splitlines()
        out: list[str] = []
        in_code = False
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i].rstrip()
            stripped = line.strip()

            if _FENCE.match(line):
                in_code = not in_code
                i += 1
                continue
            if in_code:
                out.append(_CODE(line))
                i += 1
                continue

            if "|" in line and i + 1 < n:
                block, consumed = _collect_table(lines, i)
                if consumed:
                    out.append(block)
                    i = consumed
                    continue

            if not stripped:
                out.append("")
            elif _HEADING.match(stripped):
                level, rest = _HEADING.match(stripped).groups()
                body = _inline(rest)
                out.append(_H1(body) if len(level) == 1 else _H(body))
            elif _HRULE.match(stripped):
                out.append(_HR("─" * 40))
            elif stripped.startswith(">"):
                body = _inline(stripped.lstrip(">").strip())
                out.append(_DIM("│ " + body))
            elif _ULIST.match(stripped):
                body = _inline(_ULIST.match(stripped).group(1))
                out.append(f"  {_BOLD('·')} {body}")
            elif _OLIST.match(stripped):
                body = _inline(line.lstrip())
                out.append("   " + body)
            else:
                out.append(_inline(stripped))
            i += 1
        return "\n".join(out)

def _parse_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]

def _is_delimiter(parts: list[str]) -> bool:
    return bool(parts) and all(re.fullmatch(r":?-{1,}:?", p) for p in parts)

def _collect_table(lines: list[str], start: int) -> tuple[str, int]:
    header = _parse_row(lines[start])
    if len(header) < 2 or start + 1 >= len(lines):
        return "", 0
    delim = _parse_row(lines[start + 1])
    if not _is_delimiter(delim):
        return "", 0
    end = start + 2
    rows: list[list[str]] = []
    while end < len(lines) and "|" in lines[end] and not _FENCE.match(lines[end]):
        rows.append(_parse_row(lines[end]))
        end += 1
    body = Table(headers=header, sep_style=_BOLD)
    return body(rows), end

def markdown(text: str) -> str:
    """Render the given Markdown ``text`` to styled terminal output.

    Parameters
    ----------
    text:
        The Markdown source to render.
    """
    return Markdown.render(text)
