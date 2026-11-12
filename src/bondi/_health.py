"""Bounded probes and task-local timing shared by executor backends."""

import asyncio
import math
from contextvars import ContextVar
from time import perf_counter

from pymongo.errors import ConnectionFailure, NetworkTimeout, OperationFailure

from bondi.execution import DatabaseUnavailableError

# Each workload worker resets this before an entry; concurrent calls never share timing.
_query_start_hook: ContextVar = ContextVar("query_start_hook", default=None)

_probe_timing: ContextVar[tuple[float, bool]] = ContextVar("probe_timing", default=(0.0, True))


def _validate_timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("health-check timeout_seconds must be positive and finite")


def _availability_error(error):
    # A socket timeout during a query alone does not prove loss of availability.
    if isinstance(error, DatabaseUnavailableError):
        return True
    if isinstance(error, ConnectionFailure) and not isinstance(error, NetworkTimeout):
        return True
    try:
        from couchbase.exceptions import MissingConnectionException, ServiceUnavailableException
    except ImportError:
        return False
    return isinstance(error, (MissingConnectionException, ServiceUnavailableException))


def _fatal_access_error(error):
    if isinstance(error, OperationFailure) and error.code in (13, 18):
        return True
    try:
        from couchbase.exceptions import AuthenticationException
    except ImportError:
        return False
    return isinstance(error, AuthenticationException)


async def _bounded_probe(operation, timeout_seconds, errors, propagate_errors=()):
    _validate_timeout(timeout_seconds)
    try:
        async with asyncio.timeout(timeout_seconds):
            await operation()
    except propagate_errors:
        raise
    except errors as error:
        if _fatal_access_error(error):
            raise
        raise DatabaseUnavailableError(
            f"Database unavailable or unresponsive within {timeout_seconds:g} seconds"
        ) from error


async def _preflight(executor):
    _probe_timing.set((0.0, True))
    if executor.health_check_timeout_seconds is None:
        if hook := _query_start_hook.get():
            hook()
        return 0.0
    start = perf_counter()
    success = False
    try:
        await executor.ping(timeout_seconds=executor.health_check_timeout_seconds)
        success = True
    finally:
        elapsed = (perf_counter() - start) * 1000
        _probe_timing.set((elapsed, success))
    if hook := _query_start_hook.get():
        hook()
    return elapsed


def _failure_result(error, elapsed_ms, enabled):
    from bondi.execution import ExecutionResult

    probe_ms, probe_ok = _probe_timing.get()
    if enabled and _availability_error(error) and not isinstance(error, DatabaseUnavailableError):
        original = error
        error = DatabaseUnavailableError(str(original))
        error.__cause__ = original
    return ExecutionResult(
        max(0.0, elapsed_ms - probe_ms) if probe_ok else 0.0,
        error=error,
        health_check_elapsed_ms=probe_ms,
    )
