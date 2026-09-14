from __future__ import annotations

from types import TracebackType
from typing import Any

from renus.db.core.adapter import AsyncDatabaseAdapter, TransactionContext

__all__ = ["Transaction"]

class Transaction:
    """Wrap a database transaction in async context manager semantics."""

    def __init__(self, adapter: AsyncDatabaseAdapter) -> None:
        """Initialize the transaction wrapper.

        Parameters
        ----------
        adapter:
            The database adapter that provides the transaction factory.
        """
        self.adapter = adapter
        self._tx_context: Any = None
        self._tx_iter: Any = None
        self._committed = False

    async def __aenter__(self) -> TransactionContext:
        factory_result = self.adapter.transaction_factory()
        if hasattr(factory_result, "__anext__") or hasattr(factory_result, "__aiter__"):
            self._tx_iter = factory_result
            self._tx_context = await anext(self._tx_iter)
        else:
            self._tx_context = factory_result

        if self._tx_context is not None and hasattr(self._tx_context, "__aenter__"):
            await self._tx_context.__aenter__()

        return self._tx_context

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        try:
            if exc_val is not None:
                if self._tx_context is not None and not self._committed:
                    await self._tx_context.rollback()
            else:
                if self._tx_context is not None and not self._committed:
                    await self._tx_context.commit()
                    self._committed = True

            if self._tx_context is not None and hasattr(self._tx_context, "__aexit__"):
                await self._tx_context.__aexit__(exc_type, exc_val, exc_tb)

            if self._tx_iter is not None and hasattr(self._tx_iter, "aclose"):
                await self._tx_iter.aclose()
        finally:
            self._tx_context = None

        return False
