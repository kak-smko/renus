from __future__ import annotations

from renus.config import Config

MAX_BODY_SIZE: int = Config("app").get("max_body_size", 10 * 1024 * 1024)

MAX_HEADERS: int = Config("app").get("max_headers", 100)

MAX_HEADER_SIZE: int = Config("app").get("max_headers_size", 8192)

MAX_COOKIES: int = Config("app").get("max_cookies", 50)

MAX_COOKIE_SIZE: int = Config("app").get("max_cookies_size", 4096)

MAX_QUERY_SIZE: int = Config("app").get("max_query_size", 1024)

MAX_FORM_PARTS: int = Config("app").get("max_form_parts", 1000)
