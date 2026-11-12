"""Shared scheduler; backend adapters retain their existing error conversion."""

import asyncio
import math
from time import perf_counter

from bondi._callbacks import _CallbackAbort, _ResultCallbacks
from bondi._health import _availability_error, _fatal_access_error, _query_start_hook
from bondi.load import ByPattern, LoadResult, Sequential, UniformRandom, WeightedRandom
from bondi.workload import Workload


def _duration(value, name, *, zero=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or (not zero and value == 0)
    ):
        raise ValueError(f"{name} must be {'nonnegative' if zero else 'positive'} and finite")


async def _generate_load(
    executor,
    workload,
    operation,
    *,
    selection,
    warmup_seconds,
    measurement_seconds,
    drain_timeout_seconds,
    return_load_results,
    on_result,
):
    executor._check_open()
    if not isinstance(workload, Workload):
        raise TypeError("workload must be a Workload")
    workload.validate()
    if not len(workload):
        raise ValueError("load generation requires a nonempty workload")
    for entry in workload:
        executor._validate_query(entry.query)
    if not isinstance(selection, (WeightedRandom, UniformRandom, Sequential, ByPattern)):
        raise TypeError("selection must be WeightedRandom, UniformRandom, Sequential or ByPattern")
    _duration(warmup_seconds, "warmup_seconds", zero=True)
    _duration(measurement_seconds, "measurement_seconds")
    _duration(drain_timeout_seconds, "drain_timeout_seconds")
    if not math.isfinite(warmup_seconds + measurement_seconds):
        raise ValueError("combined phase duration must be finite")
    if type(return_load_results) is not bool:
        raise TypeError("return_load_results must be a boolean")
    stream = (
        selection._prepare(workload)
        if isinstance(selection, ByPattern)
        else lambda client: selection._stream(len(workload), client)
    )
    streams = [stream(i) for i in range(executor.concurrency)]
    callbacks = _ResultCallbacks(on_result)
    returned = []
    pending = {}
    expired = []
    stop = asyncio.Event()
    next_id = 0
    origin = perf_counter()
    admission_end = origin + warmup_seconds + measurement_seconds
    stopped_at = None

    def stop_admissions():
        nonlocal stopped_at
        if stopped_at is None:
            stopped_at = min(perf_counter(), admission_end)
            stop.set()

    async def deliver(record):
        # Same ordering for retained observations and callbacks, including expiry.
        if return_load_results:
            returned.append(record)
        await callbacks.deliver(record)

    async def execute(record):
        token = _query_start_hook.set(lambda: setattr(record, "query_started", True))
        try:
            result = await operation(workload[record.workload_position].query)
            if record.stop_reason != "drain_timeout":
                record.result = result
                record.ended_seconds = perf_counter() - origin
                if result.error is not None and stopped_at is None:
                    unhealthy = executor.health_check_timeout_seconds is not None and (
                        _availability_error(result.error) or _fatal_access_error(result.error)
                    )
                    if unhealthy or not executor.continue_on_error:
                        record.stop_reason = "database_unavailable" if unhealthy else "query_error"
                        stop_admissions()
        finally:
            _query_start_hook.reset(token)
            pending.pop(record.attempt_id, None)

    async def worker(client):
        nonlocal next_id
        sequence = 0
        while not stop.is_set():
            now = perf_counter()
            if now >= admission_end:
                stop_admissions()
                break
            position = next(streams[client])
            admitted = perf_counter() - origin
            if admitted >= warmup_seconds + measurement_seconds:
                stop_admissions()
                break
            record = LoadResult(
                next_id,
                client,
                sequence,
                position,
                "warmup" if admitted < warmup_seconds else "measurement",
                admitted,
                admitted,
                False,
                None,
            )
            next_id += 1
            sequence += 1
            task = asyncio.create_task(execute(record))
            pending[record.attempt_id] = (record, task)
            try:
                await task
            except asyncio.CancelledError:
                if record.stop_reason != "drain_timeout" or asyncio.current_task().cancelling():
                    raise
            if record.stop_reason != "drain_timeout":
                await deliver(record)
            # Yield even when drivers and callbacks complete without suspending.
            await asyncio.sleep(0)

    workers = [asyncio.create_task(worker(i)) for i in range(executor.concurrency)]
    waiter = asyncio.create_task(stop.wait())
    try:
        # Observe programming/callback exceptions promptly, even during warm-up.
        while not stop.is_set():
            done, _ = await asyncio.wait(
                [waiter, *workers],
                timeout=max(0, admission_end - perf_counter()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                task.result()
            if not stop.is_set() and perf_counter() >= admission_end:
                stop_admissions()
        remaining = set(workers)
        deadline = stopped_at + drain_timeout_seconds
        while remaining and perf_counter() < deadline:
            done, remaining = await asyncio.wait(
                remaining,
                timeout=max(0, deadline - perf_counter()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                task.result()
        # Cancel operations, never callbacks for already completed results.
        ended = perf_counter() - origin
        for _, (record, task) in sorted(pending.items()):
            record.ended_seconds = ended
            record.stop_reason = "drain_timeout"
            expired.append(record)
            task.cancel()
        await asyncio.gather(*workers)
        for record in expired:
            await deliver(record)
        return returned
    except BaseException as error:
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        if isinstance(error, _CallbackAbort):
            raise error.error
        raise
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
