def _import_by_string(name):
    return __import__(f"config.{name}", fromlist=[''])

class Config:
    lists = {}

    def __init__(self, name: str) -> None:
        if name in self.lists:
            self.config = self.lists[name]
        else:
            self.config = _import_by_string(name)
            self.lists[name] = self.config

    def get(self, name:str, *default):
        return getattr(self.config,name,*default)
