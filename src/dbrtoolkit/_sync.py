"""Private lifecycle bridge for synchronous database facades."""

import asyncio
from threading import get_ident
from typing import Self


class _SyncExecutor:
    """Own one Runner and async executor, confined to the creating thread."""

    def __init__(self):
        raise TypeError("Use from_uri() to create an owned executor")

    @staticmethod
    def _no_running_loop():
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError("Use the async executor with await inside a running event loop")

    @classmethod
    def _create(cls, factory):
        cls._no_running_loop()
        self = object.__new__(cls)
        self._thread = get_ident()
        self._runner = asyncio.Runner()
        self._closed = False

        async def connect():
            return await factory()

        try:
            self._executor = self._runner.run(connect())
        except BaseException:
            self._closed = True
            self._runner.close()
            raise
        return self

    def _check(self):
        self._no_running_loop()
        if get_ident() != self._thread:
            raise RuntimeError("Use this executor only from its creating thread")
        if self._closed:
            raise RuntimeError("Executor is closed")

    def _call(self, method, *args, **kwargs):
        self._check()

        async def invoke():
            return await getattr(self._executor, method)(*args, **kwargs)

        return self._runner.run(invoke())

    def close(self) -> None:
        """Close the owned connection and event loop. Repeated calls are harmless."""
        if self._closed:
            return
        self._check()
        try:
            self._call("close")
        finally:
            self._closed = True
            self._runner.close()

    def __enter__(self) -> Self:
        self._check()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
