from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS: dict = {
    "script": "scripts",
    "iframe": "iframes",
    "object": "objects",
    "embed": "embeds",
    "form": "forms",
    "style": "styles",
    "base": "bases",
    "link": "links",
    "applet": "applets",
    "meta": "metas",
}

_ALLOWED_PROTOCOLS: tuple = ("http", "https")

_ALLOWED_ATTR: dict = {
    "class": 1,
    "id": 1,
    "http-equiv": ["meta"],
    "content": ["meta"],
    "name": ["meta"],
    "charset": ["meta"],
    "href": ["a"],
    "target": ["a"],
    "alt": ["img"],
    "width": ["img", "video"],
    "height": ["img", "video"],
    "controls": ["video"],
    "src": ["img", "video"],
}

_NO_END_TAGS: set = {"img", "hr", "br", "embed", "meta"}

class Xss(HTMLParser):

    """Sanitize HTML input to mitigate cross-site scripting attacks."""

    def __init__(self) -> None:
        """Create an XSS sanitizer with no configured options."""
        super().__init__()
        self.result: list = []
        self.start_list: list = []

    def getEscaped(self) -> str:
        """Return the escaped result of the parsed HTML content."""
        return self._htmlspecialchars("".join(self.result))

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Handle a self-closing element as a start tag."""
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Handle an opening tag, sanitizing its attributes."""
        tag = _BLOCK_TAGS.get(tag, tag)
        end_diagonal = " /" if tag in _NO_END_TAGS else ""
        if not end_diagonal:
            self.start_list.append(tag)

        allowed = {}
        for name, value in attrs:
            if name not in _ALLOWED_ATTR:
                continue
            rule = _ALLOWED_ATTR[name]
            if rule == 1 or tag in rule:
                allowed[name] = self._is_valid((name, value))

        attr_src = " ".join(
            f'{name}="{self._htmlspecialchars(value)}"' for name, value in allowed.items()
        )
        if attr_src:
            attr_src = " " + attr_src

        self.result.append(f"&lt;{tag}{attr_src}{end_diagonal}&gt;")

    def handle_endtag(self, tag: str) -> None:
        """Handle a closing tag for a previously opened element."""
        tag = _BLOCK_TAGS.get(tag, tag)
        if self.start_list and tag == self.start_list[-1]:
            self.result.append(f"&lt;/{tag}&gt;")
            self.start_list.pop()

    def handle_data(self, data: str) -> None:
        """Escape text data between tags."""
        self.result.append(self._htmlspecialchars(data))

    def handle_entityref(self, name: str) -> None:
        """Keep valid named character references."""
        if name.isalpha():
            self.result.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        """Keep valid numeric character references."""
        if name.isdigit():
            self.result.append(f"&#{name};")

    def _is_valid(self, attr: tuple) -> str:
        name, value = attr
        if name in ("href", "src"):
            if ":" in str(value):
                if not any(str(value).startswith(p) for p in _ALLOWED_PROTOCOLS):
                    return f"http://{value}"
            elif str(value).startswith("//"):
                return f"http:{value}"
        return value

    def _htmlspecialchars(self, html: str) -> str:
        return (
            html.replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#039;")
        )

