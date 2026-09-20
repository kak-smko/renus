from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from renus.db.database import Database


class Plugin:
    """Base class defining a database lifecycle and hook plugin."""

    name: str = ""
    version: str = "1.0.0"

    def __init__(self) -> None:
        """Derive the plugin name from the class name when not already set."""
        if not self.name:
            self.name = self.__class__.__name__.lower()

    async def on_install(self, db: Database) -> None:
        """Hook invoked when the plugin is installed."""
        pass

    async def on_uninstall(self, db: Database) -> None:
        """Hook invoked when the plugin is uninstalled."""
        pass

    async def on_connect(self, db: Database, connection: str) -> None:
        """Hook invoked after a database connection is opened."""
        pass

    async def on_disconnect(self, db: Database, connection: str) -> None:
        """Hook invoked when a database connection is closed."""
        pass

    async def before_query(
        self,
        db: Database,
        ast: Any,
        context: dict[str, Any],
    ) -> None:
        """Hook invoked before a query is executed."""
        pass

    async def after_query(
        self,
        db: Database,
        ast: Any,
        result: Any,
        context: dict[str, Any],
    ) -> None:
        """Hook invoked after a query completes."""
        pass

    async def before_mutation(
        self,
        db: Database,
        ast: Any,
        context: dict[str, Any],
    ) -> None:
        """Hook invoked before a mutation is executed."""
        pass

    async def after_mutation(
        self,
        db: Database,
        ast: Any,
        result: Any,
        context: dict[str, Any],
    ) -> None:
        """Hook invoked after a mutation completes."""
        pass

    async def on_error(
        self,
        db: Database,
        error: Exception,
        context: dict[str, Any],
    ) -> None:
        """Hook invoked when an error occurs during database work."""
        pass

class PluginManager:
    """Registers and dispatches lifecycle hooks to installed plugins."""

    def __init__(self, db: Database | None = None) -> None:
        """Create a plugin manager.

        Parameters
        ----------
        db:
            Optional database bound for dispatched hooks. Defaults to None.
        """
        self._db = db
        self._plugins: dict[str, Plugin] = {}

    def set_database(self, db: Database) -> None:
        """Bind the database used when dispatching hooks."""
        self._db = db

    def register(self, plugin: Plugin | type[Plugin]) -> Plugin:
        """Register a plugin instance or class and return its instance."""
        inst = plugin() if isinstance(plugin, type) else plugin
        name = inst.name.lower()
        self._plugins[name] = inst
        return inst

    def unregister(self, name_or_plugin: str | Plugin) -> Plugin | None:
        """Remove a registered plugin and return it, if present."""
        name = (
            name_or_plugin.name.lower()
            if isinstance(name_or_plugin, Plugin)
            else name_or_plugin.lower()
        )
        return self._plugins.pop(name, None)

    def get(self, name: str) -> Plugin:
        """Return the plugin registered under the given name."""
        key = name.lower()
        if key not in self._plugins:
            raise KeyError(f"Plugin '{name}' is not registered")
        return self._plugins[key]

    def has(self, name: str) -> bool:
        """Return whether a plugin is registered under the given name."""
        return name.lower() in self._plugins

    def all(self) -> list[Plugin]:
        """Return all registered plugin instances."""
        return list(self._plugins.values())

    def clear(self) -> None:
        """Remove all registered plugins."""
        self._plugins.clear()

    def discover_entry_points(
        self,
        groups: Iterable[str] = ("db.plugins", "renus.db.plugins"),
    ) -> int:
        """Discover and register plugins from the given entry-point groups.

        Returns the number of plugins registered.
        """
        discovered = 0
        for grp in groups:
            for ep in entry_points(group=grp):
                try:
                    obj = ep.load()
                    inst = obj() if isinstance(obj, type) else obj
                    if isinstance(inst, Plugin):
                        self.register(inst)
                        discovered += 1
                except Exception:
                    pass
        return discovered

    async def dispatch_connect(self, connection: str) -> None:
        """Call the on_connect hook on every registered plugin."""
        if self._db is None:
            return
        for plugin in self._plugins.values():
            await plugin.on_connect(self._db, connection)

    async def dispatch_disconnect(self, connection: str) -> None:
        """Call the on_disconnect hook on every registered plugin."""
        if self._db is None:
            return
        for plugin in self._plugins.values():
            await plugin.on_disconnect(self._db, connection)

    async def dispatch_before_query(self, ast: Any, context: dict[str, Any]) -> None:
        """Call the before_query hook on every registered plugin."""
        if self._db is None:
            return
        for plugin in self._plugins.values():
            await plugin.before_query(self._db, ast, context)

    async def dispatch_after_query(
        self,
        ast: Any,
        result: Any,
        context: dict[str, Any],
    ) -> None:
        """Call the after_query hook on every registered plugin."""
        if self._db is None:
            return
        for plugin in self._plugins.values():
            await plugin.after_query(self._db, ast, result, context)

    async def dispatch_before_mutation(self, ast: Any, context: dict[str, Any]) -> None:
        """Call the before_mutation hook on every registered plugin."""
        if self._db is None:
            return
        for plugin in self._plugins.values():
            await plugin.before_mutation(self._db, ast, context)

    async def dispatch_after_mutation(
        self,
        ast: Any,
        result: Any,
        context: dict[str, Any],
    ) -> None:
        """Call the after_mutation hook on every registered plugin."""
        if self._db is None:
            return
        for plugin in self._plugins.values():
            await plugin.after_mutation(self._db, ast, result, context)

    async def dispatch_error(self, error: Exception, context: dict[str, Any]) -> None:
        """Call the on_error hook on every registered plugin."""
        if self._db is None:
            return
        for plugin in self._plugins.values():
            await plugin.on_error(self._db, error, context)
