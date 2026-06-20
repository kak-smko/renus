from collections.abc import Callable
import re
import threading

try:
    from bson import ObjectId
except ImportError:
    ObjectId = str


def full_path_builder(app_prefix: str, path: str) -> str:
    parts = [p.strip("/") for p in [app_prefix, path] if p.strip("/")]
    return "/" + "/".join(parts) if parts else "/"

def is_safe_path(path: str) -> bool:
    if '\0' in path:
        return False
    for segment in path.split('/'):
        if segment == '..':
            return False
    
    return True

class RouteRegistry:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._routes = {}
                    cls._instance._subdomains_cache = None
        return cls._instance

    def register(self, subdomain: str, method: str, route_entry: dict):
        sub = subdomain or "_"
        with self._lock:
            if sub not in self._routes:
                self._routes[sub] = {}
            if method not in self._routes[sub]:
                self._routes[sub][method] = []
            self._routes[sub][method].append(route_entry)
            self._subdomains_cache = None
        
    def resolve(self, request, scope) -> dict|None:
        method = request.method
        if method not in ("GET", "POST", "PUT", "DELETE", "OPTIONS", "WS", "HEAD"):
            return None

        path = scope.get("path", "/")
        if path != "/":
            path = path.rstrip("/")

        if not is_safe_path(path):
            raise RuntimeError( 'Invalid path: path traversal detected')

        subdomain = getattr(request, "subdomain", "_")

        for sub in [subdomain, "_"]:
            if sub in self._routes and method in self._routes[sub]:
                for route in self._routes[sub][method]:
                    regex, params = route["regex"]
                    match = regex.fullmatch(path)
                    if match:
                        args = {k: v.convert(match.group(k)) for k, v in params.items()}
                        return _build_result(route, args)

        return None

    @property
    def all(self) -> dict:
        return self._routes

    @property
    def subdomains(self) -> list:
        if self._subdomains_cache is None:
            with self._lock:
                self._subdomains_cache = list(self._routes.keys())
        return self._subdomains_cache

    def summary(self) -> str:
        lines = []
        total = 0
        for sub, methods in sorted(self._routes.items()):
            for method, routes in sorted(methods.items()):
                for r in routes:
                    lines.append(
                        f"  {method:7s} {r['path']:40s} → {r.get('func', '?')}"
                    )
                    total += 1
        header = f"╔══ Route Registry: {total} routes registered ══╗"
        return header + "\n" + "\n".join(lines)

    def clear(self):
        with self._lock:
            self._routes.clear()
            self._subdomains_cache = None

    @classmethod
    def reset(cls):
        """Just for Test"""
        cls._instance = None


class Router:
    def __init__(
        self,
        prefix: str = "",
        middlewares: list[Callable]|None = None,
        subdomain:str|None = None,
    ) -> None:
        if middlewares is None:
            middlewares = []

        if subdomain == "_":
            raise ValueError("subdomain cannot be '_'")

        self._prefix = prefix
        self._middlewares = middlewares
        self._subdomain = subdomain or "_"
        self._registry = RouteRegistry()

    def _add(
        self, path: str, controller, func, method: str, middlewares=None, cache=None
    ):
        if middlewares is None:
            middlewares = []

        full_path = full_path_builder(self._prefix, path)
        all_middlewares = self._middlewares.copy() + middlewares

        entry = {
            "path": full_path,
            "controller": controller,
            "func": func,
            "middlewares": all_middlewares,
            "regex": build_path(full_path),
        }
        if cache:
            entry["cache"] = cache

        self._registry.register(self._subdomain, method, entry)

    def get(
        self,
        path: str,
        controller:Callable | None= None,
        func:Callable|str|None=None,
        middlewares: list[Callable]|None = None,
        cache: int|None = None,
    ):
        self._add(path, controller, func, "GET", middlewares, cache)
        return self

    def head(
        self,
        path: str,
        controller:Callable | None= None,
        func:Callable|str|None=None,
        middlewares: list[Callable]|None = None,
        cache: int|None = None,
    ):
        self._add(path, controller, func, "HEAD", middlewares, cache)
        return self

    def post(
        self,
        path: str,
        controller:Callable | None= None,
        func:Callable|str|None=None,
        middlewares: list[Callable]|None = None,
    ):
        self._add(path, controller, func, "POST", middlewares)
        return self

    def put(
        self,
        path: str,
        controller:Callable | None= None,
        func:Callable|str|None=None,
        middlewares: list[Callable]|None = None,
    ):
        self._add(path, controller, func, "PUT", middlewares)
        return self

    def delete(
        self,
        path: str,
        controller:Callable | None= None,
        func:Callable|str|None=None,
        middlewares: list[Callable]|None = None,
    ):
        self._add(path, controller, func, "DELETE", middlewares)
        return self

    def option(
        self,
        path: str,
        controller:Callable | None= None,
        func:Callable|str|None=None,
        middlewares: list[Callable]|None = None,
    ):
        self._add(path, controller, func, "OPTIONS", middlewares)
        return self

    def ws(
        self,
        path: str,
        controller:Callable | None= None,
        func:Callable|str|None=None,
        middlewares: list[Callable]|None = None,
    ):
        self._add(path, controller, func, "WS", middlewares)
        return self

    def crud(
        self,
        path: str,
        controller:Callable | None= None,
        middlewares: list[Callable]|None = None,
        func_prefix: str = "",
    ):
        self._add(path, controller, f"{func_prefix}index", "GET", middlewares)
        self._add(path, controller, f"{func_prefix}store", "POST", middlewares)
        self._add(
            path + "/{id:oid}", controller, f"{func_prefix}update", "PUT", middlewares
        )
        self._add(
            path + "/{id:oid}",
            controller,
            f"{func_prefix}delete",
            "DELETE",
            middlewares,
        )
        return self

    def mcud(
        self,
        path: str,
        controller:Callable | None= None,
        middlewares: list[Callable]|None = None,
        func_prefix: str = "",
    ):
        self._add(path, controller, f"{func_prefix}m_store", "POST", middlewares)
        self._add(path, controller, f"{func_prefix}m_update", "PUT", middlewares)
        self._add(path, controller, f"{func_prefix}m_delete", "DELETE", middlewares)
        return self


def _build_result(route: dict, args: dict) -> dict:
    """ساخت نتیجه route match شده"""
    return {
        "path": route["path"],
        "args": args,
        "controller": route["controller"],
        "func": route["func"],
        "middlewares": route["middlewares"],
        "cache": route.get("cache", None),
    }


PARAM_REGEX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(:[^/\{]*)?\}")


class StringConvertor:
    regex = r"[^/]+"

    def convert(self, value: str) -> str:
        return str(value)


class PathConvertor:
    regex = r"[^/]+(?:/[^/]+)*"

    def convert(self, value: str) -> str:
        return str(value)


class IntegerConvertor:
    regex = r"[0-9]+"

    def convert(self, value: str) -> int:
        return int(value)


class FloatConvertor:
    regex = r"[0-9]+(\.[0-9]+)?"

    def convert(self, value: str) -> float:
        return float(value)


class OIdConvertor:
    regex = r"[a-f0-9]{24}"

    def convert(self, value: str):
        return ObjectId(value)


class BoolConvertor:
    regex = r"(true)|(false)"

    def convert(self, value: str) -> bool:
        return value == "true"


CONVERTOR_TYPES = {
    "str": StringConvertor(),
    "int": IntegerConvertor(),
    "float": FloatConvertor(),
    "path": PathConvertor(),
    "oid": OIdConvertor(),
    "bool": BoolConvertor(),
}


def build_path(path: str):
    path_regex = ""
    idx = 0
    param_convertors = {}

    for match in PARAM_REGEX.finditer(path):
        param_name, convertor_type = match.groups("str")
        convertor_type = convertor_type.lstrip(":")
        path_regex += re.escape(path[idx : match.start()])

        if convertor_type in CONVERTOR_TYPES:
            convertor = CONVERTOR_TYPES[convertor_type]
            path_regex += f"(?P<{param_name}>{convertor.regex})"
            param_convertors[param_name] = convertor
        else:
            path_regex += f"(?P<{param_name}>{convertor_type})"
            param_convertors[param_name] = CONVERTOR_TYPES["str"]

        idx = match.end()

    path_regex += re.escape(path[idx:]) + ""
    return re.compile(path_regex), param_convertors
