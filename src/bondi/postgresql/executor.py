"""Asynchronous PostgreSQL read workloads using a bounded Psycopg pool."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from functools import partial
from time import perf_counter
from typing import TYPE_CHECKING, Self

from bondi._callbacks import _CallbackAbort, _ResultCallback, _ResultCallbacks
from bondi._health import _bounded_probe, _failure_result, _preflight, _validate_timeout
from bondi._load import _generate_load
from bondi.connection import PostgresConnection
from bondi.execution import DatabaseUnavailableError, ExecutionResult
from bondi.load import LoadCallback, LoadResult, Selection
from bondi.workload import Workload

from .query import PostgresQuery

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool


class AsyncPostgresExecutor:
    """Execute single read queries using a borrowed async pool or from_connection().

    Each active operation checks out its own connection. Workload results retain
    input order. Use an idle, transaction-ready pool on the current event loop.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
        health_check_timeout_seconds: float | None = None,
    ):
        try:
            import psycopg
            import psycopg_pool
        except ImportError:
            raise ImportError("Install bondi[postgresql] for PostgreSQL execution") from None
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        if type(continue_on_error) is not bool:
            raise TypeError("continue_on_error must be a boolean")
        for timeout in (timeout_seconds, health_check_timeout_seconds):
            if timeout is not None:
                _validate_timeout(timeout)
        self._driver = psycopg
        self._pool_timeout = psycopg_pool.PoolTimeout
        self.pool = pool
        self.concurrency = concurrency
        self.continue_on_error = continue_on_error
        self.timeout_seconds = timeout_seconds
        self.health_check_timeout_seconds = health_check_timeout_seconds
        self._owned = False
        self._closed = False

    @classmethod
    async def from_connection(
        cls,
        connection: PostgresConnection,
        *,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
        health_check_timeout_seconds: float | None = None,
    ) -> Self:
        """Open an owned pool and wait for the first authenticated connection."""
        if not isinstance(connection, PostgresConnection):
            raise TypeError("Expected PostgresConnection")
        try:
            from psycopg_pool import AsyncConnectionPool
        except ImportError:
            raise ImportError("Install bondi[postgresql] for PostgreSQL execution") from None

        kwargs = {
            key: value
            for key, value in (("user", connection.username), ("password", connection.password))
            if value is not None
        }
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        pool = AsyncConnectionPool(
            connection.uri, kwargs=kwargs, min_size=1, max_size=concurrency, open=False
        )
        self = cls(
            pool,
            concurrency=concurrency,
            continue_on_error=continue_on_error,
            timeout_seconds=timeout_seconds,
            health_check_timeout_seconds=health_check_timeout_seconds,
        )
        self._owned = True
        try:
            await self.pool.open(wait=True)
        except BaseException:
            await self.close()
            raise
        return self

    async def close(self):
        """Release the owned pool and finish using this executor."""
        if self._owned and not self._closed:
            await self.pool.close()
        self._closed = True

    def _check_open(self):
        if self._closed:
            raise RuntimeError("Executor is closed")

    async def __aenter__(self):
        self._check_open()
        return self

    async def __aexit__(self, *args):
        await self.close()

    def _validate_query(self, query):
        if not isinstance(query, PostgresQuery):
            raise TypeError("Expected PostgresQuery")
        query.validate()

    async def ping(self, *, timeout_seconds: float = 5):
        """Check pool acquisition and a SQL round trip under an independent deadline."""
        self._check_open()

        async def probe():
            async with self.pool.connection() as conn:
                await conn.execute("SELECT 1")

        await _bounded_probe(probe, timeout_seconds, (self._driver.Error, TimeoutError))

    async def run(self, query: PostgresQuery, *, collect_results: bool = False) -> ExecutionResult:
        """Consume every row, optionally retaining dictionaries keyed by SQL labels."""
        if type(collect_results) is not bool:
            raise TypeError("collect_results must be a boolean")
        return await self._execute(query, "run", collect_results)

    async def explain(self, query: PostgresQuery) -> ExecutionResult:
        """Collect an estimated JSON plan."""
        return await self._execute(query, "explain", False)

    async def profile(self, query: PostgresQuery) -> ExecutionResult:
        """Execute once with ANALYZE and BUFFERS and retain the native JSON plan."""
        return await self._execute(query, "profile", False)

    async def _execute(self, query, mode, collect):
        from psycopg.rows import tuple_row
        from psycopg.types.json import set_json_loads

        self._check_open()
        self._validate_query(query)
        probe_ms = await _preflight(self)
        start = perf_counter()
        params = query.positional_parameters or None
        result = ExecutionResult(0, health_check_elapsed_ms=probe_ms)
        try:
            async with asyncio.timeout(self.timeout_seconds), self.pool.connection() as conn:
                async with (
                    conn.transaction(force_rollback=True),
                    conn.cursor(row_factory=tuple_row) as cur,
                ):
                    await cur.execute("SET TRANSACTION READ ONLY")
                    # Optimize for consuming the whole cursor, including for diagnostic plans.
                    await cur.execute("SET LOCAL cursor_tuple_fraction = 1")
                    declare = "DECLARE bondi_rows NO SCROLL CURSOR FOR " + query.statement
                    if mode == "run":
                        await cur.execute(declare, params, prepare=True)
                        set_json_loads(partial(json.loads, parse_float=Decimal), cur)
                        result.row_count = 0
                        result.documents = [] if collect else None
                        labels = None
                        while True:
                            await cur.execute("FETCH FORWARD 256 FROM bondi_rows")
                            if collect and labels is None:
                                labels = [col.name for col in cur.description]
                                if len(set(labels)) != len(labels):
                                    raise ValueError(
                                        "Use unique SQL output labels to collect results"
                                    )
                            rows = await cur.fetchall()
                            result.row_count += len(rows)
                            if collect:
                                result.documents.extend(
                                    dict(zip(labels, row, strict=True)) for row in rows
                                )
                            if len(rows) < 256:
                                break
                    else:
                        options = (
                            "FORMAT JSON" if mode == "explain" else "ANALYZE, BUFFERS, FORMAT JSON"
                        )
                        await cur.execute(f"EXPLAIN ({options}) " + declare, params, prepare=True)
                        result.raw = {"explain": (await cur.fetchone())[0]}
        except self._pool_timeout as error:
            raise TimeoutError("PostgreSQL pool acquisition timed out") from error
        result.elapsed_ms = (perf_counter() - start) * 1000
        return result

    async def _observe(self, operation, query):
        start = perf_counter()
        try:
            return await operation(query)
        except (self._driver.Error, TimeoutError, DatabaseUnavailableError) as error:
            enabled = self.health_check_timeout_seconds is not None
            state = getattr(error, "sqlstate", None) or ""
            if enabled and (
                state.startswith(("08", "28"))
                or state in {"42501", "57P01", "57P02", "57P03"}
                or isinstance(error, self._driver.OperationalError)
                and not state
            ):
                failure = DatabaseUnavailableError("PostgreSQL availability or access failure")
                failure.__cause__ = error
                error = failure
            return _failure_result(error, (perf_counter() - start) * 1000, enabled)

    async def generate_load(
        self,
        workload: Workload,
        *,
        selection: Selection,
        measurement_seconds: float,
        drain_timeout_seconds: float,
        warmup_seconds: float = 0,
        collect_results: bool = False,
        return_load_results: bool = True,
        on_result: LoadCallback | None = None,
    ) -> list[LoadResult]:
        """Generate sustained load using BONDI's shared scheduler and drain policy."""
        if type(collect_results) is not bool:
            raise TypeError("collect_results must be a boolean")
        operation = partial(self.run, collect_results=collect_results)
        return await _generate_load(
            self,
            workload,
            partial(self._observe, operation),
            selection=selection,
            measurement_seconds=measurement_seconds,
            drain_timeout_seconds=drain_timeout_seconds,
            warmup_seconds=warmup_seconds,
            return_load_results=return_load_results,
            on_result=on_result,
        )

    async def run_workload(
        self,
        workload: Workload,
        *,
        collect_results: bool = False,
        on_result: _ResultCallback | None = None,
    ) -> list[ExecutionResult | None]:
        """Run entries with bounded concurrency and input-aligned results."""
        if type(collect_results) is not bool:
            raise TypeError("collect_results must be a boolean")
        return await self._workload(
            workload, partial(self.run, collect_results=collect_results), on_result
        )

    async def explain_workload(
        self, workload: Workload, *, on_result: _ResultCallback | None = None
    ) -> list[ExecutionResult | None]:
        """Explain each workload entry."""
        return await self._workload(workload, self.explain, on_result)

    async def profile_workload(
        self, workload: Workload, *, on_result: _ResultCallback | None = None
    ) -> list[ExecutionResult | None]:
        """Profile each workload entry."""
        return await self._workload(workload, self.profile, on_result)

    async def _workload(self, workload, operation, on_result):
        self._check_open()
        if not isinstance(workload, Workload):
            raise TypeError("Expected Workload")
        workload.validate()
        for entry in workload:
            self._validate_query(entry.query)
        callbacks = _ResultCallbacks(on_result)
        results = [None] * len(workload)
        entries = iter(enumerate(workload))
        stopped = False

        async def worker():
            nonlocal stopped
            while not stopped:
                item = next(entries, None)
                if item is None:
                    return
                index, entry = item
                result = await self._observe(operation, entry.query)
                results[index] = result
                if result.error and (
                    not self.continue_on_error or isinstance(result.error, DatabaseUnavailableError)
                ):
                    stopped = True
                try:
                    await callbacks.deliver(index, entry, result)
                except BaseException:
                    stopped = True
                    raise

        workers = [
            asyncio.create_task(worker()) for _ in range(min(self.concurrency, len(workload)))
        ]
        try:
            await asyncio.gather(*workers)
        except BaseException as error:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            if isinstance(error, _CallbackAbort):
                raise error.error
            raise
        return results
