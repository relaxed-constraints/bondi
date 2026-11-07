"""Private background-loop bridge for synchronous database facades."""

import asyncio
import inspect
from concurrent.futures import Future
from queue import Queue
from threading import Event, Thread, get_ident
from typing import Self


class _SyncExecutor:
    """Own an async executor on a background loop; calls stay on the owner thread."""

    def __init__(self):
        raise TypeError("Use from_uri() to create an owned executor")

    @classmethod
    def _create(cls, factory):
        self = object.__new__(cls)
        self._thread = get_ident()
        self._closed = False
        self._in_callback = False
        self._executor = None
        ready = Event()

        def serve():
            with asyncio.Runner() as runner:
                self._loop = runner.get_loop()
                ready.set()
                self._loop.run_forever()

        self._worker = Thread(target=serve, name=f"bondi-{cls.__name__}", daemon=True)
        self._worker.start()
        ready.wait()

        async def connect():
            self._executor = await factory()

        try:
            self._submit(connect)
        except BaseException:
            try:
                if self._executor is not None:
                    self._submit(self._executor.close, cancel_on_interrupt=False)
            finally:
                self._shutdown()
            raise
        return self

    def _check(self):
        if get_ident() != self._thread:
            raise RuntimeError("Use this executor only from its creating thread")
        if self._closed:
            raise RuntimeError("Executor is closed")
        if self._in_callback:
            raise RuntimeError("Cannot call the same executor from its result callback")

    def _submit(self, operation, *, cancel_on_interrupt=True, callbacks=None):
        """Wait for an operation, including its cancellation cleanup on interrupt."""
        self._check()
        outcome = Future()
        task = None

        async def invoke():
            try:
                value = await operation()
            except BaseException as error:
                outcome.set_exception(error)
            else:
                outcome.set_result(value)

        def start():
            nonlocal task
            task = self._loop.create_task(invoke())

        def cancel():
            if task is not None and not task.done():
                # Schedule after the already-queued first task step.
                self._loop.call_soon(task.cancel)

        if callbacks is not None:
            outcome.add_done_callback(lambda _: callbacks.put(None))
        self._loop.call_soon_threadsafe(start)
        try:
            if callbacks is not None:
                while (request := callbacks.get()) is not None:
                    callback, args, reply = request
                    if not reply.set_running_or_notify_cancel():
                        continue
                    self._in_callback = True
                    try:
                        returned = callback(*args)
                        if inspect.isawaitable(returned):
                            if inspect.iscoroutine(returned):
                                returned.close()
                            raise TypeError("Synchronous on_result must not return an awaitable")
                    except KeyboardInterrupt:
                        # Let the outer interrupt handler cancel and drain the workload.
                        reply.cancel()
                        raise
                    except BaseException as error:
                        reply.set_exception(error)
                    else:
                        reply.set_result(None)
                    finally:
                        self._in_callback = False
            return outcome.result()
        except KeyboardInterrupt:
            if cancel_on_interrupt:
                self._loop.call_soon_threadsafe(cancel)
            # Do not return control until the coroutine has finished unwinding.
            while not outcome.done():
                try:
                    outcome.result(timeout=0.1)
                except (KeyboardInterrupt, TimeoutError):
                    continue
                except BaseException:
                    break
            raise

    def _call(self, method, *args, **kwargs):
        async def invoke():
            return await getattr(self._executor, method)(*args, **kwargs)

        return self._submit(invoke)

    def _call_workload(self, method, *args, on_result=None, **kwargs):
        self._check()
        if on_result is None:
            return self._call(method, *args, **kwargs)
        if not callable(on_result):
            raise TypeError("on_result must be callable or None")
        if inspect.iscoroutinefunction(on_result) or inspect.iscoroutinefunction(
            getattr(on_result, "__call__", None)
        ):
            raise TypeError("Synchronous on_result must not be an async callback")
        callbacks = Queue()

        async def deliver(*callback_args):
            reply = Future()
            callbacks.put((on_result, callback_args, reply))
            await asyncio.wrap_future(reply)

        async def invoke():
            return await getattr(self._executor, method)(*args, on_result=deliver, **kwargs)

        return self._submit(invoke, callbacks=callbacks)

    def _shutdown(self):
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        while self._worker.is_alive():
            try:
                self._worker.join(timeout=0.1)
            except KeyboardInterrupt:
                continue

    def close(self) -> None:
        """Close the connection, stop its loop and join its thread; idempotent."""
        if self._closed:
            return
        self._check()
        try:
            self._submit(self._executor.close, cancel_on_interrupt=False)
        finally:
            self._shutdown()

    def __enter__(self) -> Self:
        self._check()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
