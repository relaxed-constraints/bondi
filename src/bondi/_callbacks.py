"""Per-workload callback serialization, shared by database backends."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from bondi.execution import ExecutionResult
from bondi.workload import WorkloadEntry

_ResultCallback = Callable[[int, WorkloadEntry, ExecutionResult], None | Awaitable[None]]
_SyncResultCallback = Callable[[int, WorkloadEntry, ExecutionResult], None]


class _CallbackAbort(Exception):
    """Carry process-control exceptions through worker tasks without stopping their loop."""

    def __init__(self, error: BaseException):
        self.error = error
        super().__init__(str(error))


class _ResultCallbacks:
    def __init__(self, callback: _ResultCallback | None):
        if callback is not None and not callable(callback):
            raise TypeError("on_result must be callable or None")
        self.callback = callback
        self.lock = asyncio.Lock()
        self.failed = False

    async def deliver(self, *args):
        if self.callback is None:
            return
        async with self.lock:
            # A failed delivery aborts the call, including callbacks waiting for this lock.
            if self.failed:
                return
            try:
                returned = self.callback(*args)
                if inspect.isawaitable(returned):
                    await returned
            except (KeyboardInterrupt, SystemExit) as error:
                self.failed = True
                raise _CallbackAbort(error) from error
            except BaseException:
                self.failed = True
                raise
