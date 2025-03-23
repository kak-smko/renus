import re
import typing

try:
    from bson import ObjectId
except:
    def ObjectId(s):
        return s


def full_path_builder(app_prefix: str, path: str):
    app_prefix = app_prefix.strip(' /')
    path = path.strip(' /')
    full = ''
    if app_prefix != '':
        full += '/' + app_prefix
    full = full.strip(' /')
    full = full.strip(' /')
    if path != '':
        full += '/' + path
    return '/' + full.strip(' /')


class BaseRoute:
    _routes = {}
    _route_store = {}

    def __init__(self, scope, prefix: str = '', middlewares=None, subdomain=None, shared=False) -> None:
        if middlewares is None:
            middlewares = []

        if subdomain == '_' or subdomain == '__':
            raise "subdomain cannot be '_'"

        self._scope = scope
        self._app_prefix = prefix
        self._middlewares = middlewares
        self._subdomain = subdomain or '_'
        if shared:
            self._subdomain = "__"

        if self._subdomain not in self._routes:
            self._routes[self._subdomain] = {}

        for m in ['POST', 'GET', 'PUT', 'OPTIONS', 'DELETE', 'WS']:
            if m not in self._routes[self._subdomain]:
                self._routes[self._subdomain][m] = []

    def _add(self, path: str, controller: typing.Callable, func: typing.Union[str, typing.Callable], method: str,
             middlewares=None, cache=None):
        if middlewares is None:
            middlewares = []
        full_path = full_path_builder(self._app_prefix, path)
        middlwrs = self._middlewares.copy()

        r = {
            'path': full_path,
            'controller': controller,
            'func': func,
            'middlewares': middlwrs + middlewares,
            'regex': build_path(full_path)
        }
        if cache:
            r['cache'] = cache
        self._routes[self._subdomain][method].append(r)

    @property
    def all(self):
        return self._routes

    @property
    def subdomains(self):
        if self._route_store.get('_subdomains', False) is False:
            self._route_store['_subdomains'] = list(self._routes.keys())

        return self._route_store['_subdomains']

    def __request_subdomain(self, request):
        if len(self.subdomains) == 1:
            return self.subdomains[0]

        return request.subdomain or '_'

    def response(self, request):
        method = request.method
        if method not in ['POST', 'GET', 'PUT', 'OPTIONS', 'DELETE', 'WS']:
            return False

        if self._scope['path'] != '/':
            self._scope['path'] = self._scope['path'].rstrip(' /')

        path = self._scope['path']

        subdomain = self.__request_subdomain(request)

        if subdomain not in self._routes:
            return False

        if "__" in self._routes:
            for route in self._routes["__"][method]:
                regex, params = route['regex']
                find = regex.search(path)
                if find:
                    args = {}
                    for key, value in params.items():
                        args[key] = value.convert(find.group(key))
                    return build(route, args)

        for route in self._routes[subdomain][method]:
            regex, params = route['regex']
            find = regex.search(path)
            if find:
                args = {}
                for key, value in params.items():
                    args[key] = value.convert(find.group(key))
                return build(route, args)

        return False


class Router(BaseRoute):
    def __init__(self, scope=None, prefix: str = '', middlewares: typing.List[typing.Callable] = None,
                 subdomain: str = None, shared: bool = False) -> None:
        if middlewares is None:
            middlewares = []
        super().__init__(scope, prefix, middlewares, subdomain, shared)

    def get(self, path, controller: typing.Callable = None, func: typing.Union[str, typing.Callable] = None,
            middlewares: typing.List[typing.Callable] = None, cache=None):
        self._add(path, controller, func, 'GET', middlewares, cache)
        return self

    def post(self, path, controller: typing.Callable = None, func: typing.Union[str, typing.Callable] = None,
             middlewares: typing.List[typing.Callable] = None):
        self._add(path, controller, func, 'POST', middlewares)
        return self

    def put(self, path, controller: typing.Callable = None, func: typing.Union[str, typing.Callable] = None,
            middlewares: typing.List[typing.Callable] = None):
        self._add(path, controller, func, 'PUT', middlewares)
        return self

    def option(self, path, controller: typing.Callable = None, func: typing.Union[str, typing.Callable] = None,
               middlewares: typing.List[typing.Callable] = None):
        self._add(path, controller, func, 'OPTIONS', middlewares)
        return self

    def delete(self, path, controller: typing.Callable = None, func: typing.Union[str, typing.Callable] = None,
               middlewares: typing.List[typing.Callable] = None):
        self._add(path, controller, func, 'DELETE', middlewares)
        return self

    def ws(self, path, controller: typing.Callable = None, func: typing.Union[str, typing.Callable] = None,
           middlewares: typing.List[typing.Callable] = None):
        self._add(path, controller, func, 'WS', middlewares)
        return self

    def crud(self, path, controller: typing.Callable = None, middlewares: typing.List[typing.Callable] = None):
        self._add(path, controller, 'index', 'GET', middlewares)
        self._add(path, controller, 'store', 'POST', middlewares)
        self._add(path + '/{id:oid}', controller, 'update', 'PUT', middlewares)
        self._add(path + '/{id:oid}', controller, 'delete', 'DELETE', middlewares)
        return self

    def mcud(self, path, controller: typing.Callable = None, middlewares: typing.List[typing.Callable] = None):
        self._add(path, controller, 'm_store', 'POST', middlewares)
        self._add(path, controller, 'm_update', 'PUT', middlewares)
        self._add(path, controller, 'm_delete', 'DELETE', middlewares)
        return self


def build(route, args):
    res = {}
    res['path'] = route['path']
    res['args'] = args
    res['controller'] = route['controller']
    res['func'] = route['func']
    res['middlewares'] = route['middlewares']
    res['cache'] = route.get('cache', None)
    return res


PARAM_REGEX = re.compile("{([a-zA-Z_][a-zA-Z0-9_]*)(:[^/{]*)?}")


class StringConvertor:
    regex = r"[^/]+"

    def convert(self, value: str) -> str:
        return value


class PathConvertor:
    regex = r".*"

    def convert(self, value: str) -> str:
        return str(value)


class IntegerConvertor:
    regex = r"[0-9]+"

    def convert(self, value: str) -> int:
        return int(value)


class FloatConvertor:
    regex = r"[0-9]+(.[0-9]+)?"

    def convert(self, value: str) -> float:
        return float(value)


class OIdConvertor:
    regex = r"[a-f\d]{24}"

    def convert(self, value: str) -> ObjectId:
        return ObjectId(value)


class BoolConvertor:
    regex = r"(true)|(false)"

    def convert(self, value: str) -> bool:
        return bool(value)


CONVERTOR_TYPES = {
    "str": StringConvertor(),
    "int": IntegerConvertor(),
    "float": FloatConvertor(),
    "path": PathConvertor(),
    "oid": OIdConvertor(),
    "bool": BoolConvertor()
}


def build_path(
        path: str,
):
    path_regex = "^"
    idx = 0
    param_convertors = {}
    for match in PARAM_REGEX.finditer(path):
        param_name, convertor_type = match.groups("str")
        convertor_type = convertor_type.lstrip(":")
        path_regex += re.escape(path[idx: match.start()])
        if convertor_type in CONVERTOR_TYPES:
            convertor = CONVERTOR_TYPES[convertor_type]
            path_regex += f"(?P<{param_name}>{convertor.regex})"
            param_convertors[param_name] = convertor
        else:
            path_regex += f"(?P<{param_name}>{convertor_type})"
            param_convertors[param_name] = CONVERTOR_TYPES['str']

        idx = match.end()

    path_regex += re.escape(path[idx:]) + "$"

    return re.compile(path_regex), param_convertors
