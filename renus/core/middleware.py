class Middleware:
    def __init__(self, request, middlewares=None) -> None:
        self.middlewares = [] if middlewares is None else middlewares
        self.request = request

    def next(self):
        for middleware in self.middlewares:
            handle = middleware(self.request)
            if handle is True:
                continue
            return handle
        return True
