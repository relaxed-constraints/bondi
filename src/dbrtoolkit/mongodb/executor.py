"""Async MongoDB operations and bounded workload scheduling."""

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from time import perf_counter
from typing import Any, Literal, Self

import pymongo
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

from dbrtoolkit.execution import ExecutionResult
from dbrtoolkit.mongodb.aggregate import MongoAggregateQuery
from dbrtoolkit.mongodb.query import MongoFindQuery
from dbrtoolkit.workload import Workload

MongoQuery = MongoFindQuery | MongoAggregateQuery
ProfileVerbosity = Literal["executionStats", "allPlansExecution"]

# Driver/server operation failures are data; invalid API use and programming
# errors (TypeError, ConfigurationError, InvalidOperation, etc.) must propagate.
_OPERATION_ERRORS = (ConnectionFailure, OperationFailure, TimeoutError)
_QUERY_FIELDS = {
    "filter",
    "projection",
    "sort",
    "skip",
    "limit",
    "pipeline",
    "find",
    "aggregate",
    "collection",
    "database",
    "target",
    "$db",
    "explain",
    "verbosity",
    "cursor",
}
_COMMAND_FIELDS = _QUERY_FIELDS | {"command", "value", "check", "allowable_errors"}


def _options(value: Mapping[str, Any] | None, forbidden: set[str], name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise TypeError(f"{name} must be a mapping with string keys")
    conflicts = forbidden.intersection(value)
    if conflicts:
        raise ValueError(f"{name} overrides reserved fields: {', '.join(sorted(conflicts))}")
    return dict(value)


class AsyncMongoDBExecutor:
    """Run, explain and profile native queries and single-backend workloads using PyMongo async.

    Args:
        client: Borrowed AsyncMongoClient; caller retains ownership and closes it.
        concurrency: Maximum in-flight entries per workload call; positive integer.
        continue_on_error: Whether to schedule remaining entries after an operation error.
        timeout_seconds: Optional positive, finite deadline shared by the operation
            and all cursor batches. None leaves client timeout configuration in effect.

    Use from_uri() and async with for an owned client. The client and executor must
    stay on one event loop. Inputs are retained by reference: do not modify queries,
    workloads or option contents while a call is running. No write-stage guard or
    additional retries are added. Database permissions govern allowed operations.
    """

    def __init__(
        self,
        client: AsyncMongoClient,
        *,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        if type(continue_on_error) is not bool:
            raise TypeError("continue_on_error must be a boolean")
        if timeout_seconds is not None and (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite, or None")
        self.client = client
        self.concurrency = concurrency
        self.continue_on_error = continue_on_error
        self.timeout_seconds = timeout_seconds
        self._owns_client = False
        self._closed = False

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an owned async client; pass native client_kwargs to PyMongo.

        Validates executor options before allocating the client. Use async with
        or await close() for cleanup. Creating the executor does not ping MongoDB.
        """
        options = _options(client_kwargs, {"host"}, "client_kwargs")
        executor = cls(
            None,
            concurrency=concurrency,
            continue_on_error=continue_on_error,
            timeout_seconds=timeout_seconds,
        )
        executor.client = AsyncMongoClient(uri, **options)
        executor._owns_client = True
        return executor

    async def close(self) -> None:
        """Close an owned client once; leave a borrowed client open.

        Close after active calls finish. A closed owned executor cannot be reused.
        """
        if self._owns_client and not self._closed:
            await self.client.close()
            self._closed = True

    async def __aenter__(self) -> Self:
        self._check_open()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Executor is closed")

    def _validate_query(self, query: MongoQuery) -> None:
        self._check_open()
        if not isinstance(query, (MongoFindQuery, MongoAggregateQuery)):
            raise TypeError("Expected MongoFindQuery or MongoAggregateQuery")
        query.validate()

    def _timeout(self):
        return (
            pymongo.timeout(self.timeout_seconds)
            if self.timeout_seconds is not None
            else nullcontext()
        )

    @staticmethod
    def _profile_verbosity(value: str) -> None:
        if value not in ("executionStats", "allPlansExecution"):
            raise ValueError("Unsupported profile verbosity")

    async def run(
        self,
        query: MongoQuery,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Fully consume a find/aggregation cursor, optionally retaining documents.

        query_kwargs uses native PyMongo find/aggregate keyword names and cannot
        override represented query fields. Operation exceptions propagate directly.
        Timing excludes validation and scheduling, includes consumption and cursor
        cleanup. Failed partial results are discarded. Cursors close on all exits.
        """
        self._validate_query(query)
        if type(collect_results) is not bool:
            raise TypeError("collect_results must be a boolean")
        options = _options(query_kwargs, _QUERY_FIELDS, "query_kwargs")
        collection = self.client[query.target.database][query.target.collection]
        documents = [] if collect_results else None
        count = 0
        cursor = None
        failed = False
        start = perf_counter()
        try:
            with self._timeout():
                if isinstance(query, MongoFindQuery):
                    cursor = collection.find(
                        filter=query.filter,
                        projection=query.projection,
                        sort=list(query.sort) or None,
                        skip=query.skip,
                        limit=query.limit or 0,
                        **options,
                    )
                else:
                    cursor = await collection.aggregate(query.pipeline, **options)
                async for document in cursor:
                    count += 1
                    if documents is not None:
                        documents.append(document)
        except BaseException:
            failed = True
            raise
        finally:
            if cursor is not None:
                try:
                    # Cleanup occurs outside the expired operation deadline.
                    await cursor.close()
                except Exception:
                    if not failed:
                        raise
        return ExecutionResult(
            (perf_counter() - start) * 1000, row_count=count, documents=documents
        )

    async def explain(
        self,
        query: MongoQuery,
        *,
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Collect a planning-only queryPlanner explain in result.raw.

        Does not execute the winning plan for execution statistics. Native inner
        command options go in query_kwargs; outer command options (e.g. maxTimeMS)
        go in command_kwargs. Reserved fields cannot override the operation mode.
        Parsing is explicit. Driver/server exceptions propagate.
        """
        return await self._explain_command(query, "queryPlanner", query_kwargs, command_kwargs)

    async def profile(
        self,
        query: MongoQuery,
        *,
        verbosity: ProfileVerbosity = "executionStats",
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an instrumented explain and retain its diagnostics in result.raw.

        Defaults to executionStats; allPlansExecution also includes candidate-plan
        trial statistics. This does not enable MongoDB's database profiler. It returns
        no query documents or row_count; use summarize(raw) explicitly for
        server counts. elapsed_ms measures this diagnostic request, not ordinary run
        latency. Options and exception handling follow explain().
        """
        self._profile_verbosity(verbosity)
        return await self._explain_command(query, verbosity, query_kwargs, command_kwargs)

    async def _explain_command(
        self,
        query: MongoQuery,
        verbosity: str,
        query_kwargs: Mapping[str, Any] | None,
        command_kwargs: Mapping[str, Any] | None,
    ) -> ExecutionResult:
        self._validate_query(query)
        inner_options = _options(query_kwargs, _QUERY_FIELDS, "query_kwargs")
        outer_options = _options(command_kwargs, _COMMAND_FIELDS, "command_kwargs")
        if isinstance(query, MongoFindQuery):
            inner = {"find": query.target.collection, "filter": query.filter}
            for name, value in (
                ("projection", query.projection),
                ("sort", dict(query.sort) or None),
                ("skip", query.skip),
                ("limit", query.limit),
            ):
                if value is not None:
                    inner[name] = value
        else:
            inner = {"aggregate": query.target.collection, "pipeline": query.pipeline, "cursor": {}}
        inner.update(inner_options)
        db = self.client[query.target.database]
        start = perf_counter()
        with self._timeout():
            response = await db.command({"explain": inner, "verbosity": verbosity}, **outer_options)
        return ExecutionResult((perf_counter() - start) * 1000, raw=response)

    async def run_workload(
        self,
        workload: Workload,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Run entries with bounded concurrency and return input-aligned outcomes.

        Same options apply to every entry. None means not started. Expected database
        and timeout failures become results with error set. If continue_on_error is
        False, stop scheduling after observing failure but drain in-flight operations.
        Programming errors and caller cancellation propagate after worker cleanup.
        """
        if type(collect_results) is not bool:
            raise TypeError("collect_results must be a boolean")
        options = _options(query_kwargs, _QUERY_FIELDS, "query_kwargs")
        return await self._workload(
            workload,
            lambda query: self.run(query, collect_results=collect_results, query_kwargs=options),
        )

    async def explain_workload(
        self,
        workload: Workload,
        *,
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Collect planning-only explains with run_workload's scheduling/error policy.

        Validate all query types and reserved options before issuing operations.
        """
        inner = _options(query_kwargs, _QUERY_FIELDS, "query_kwargs")
        outer = _options(command_kwargs, _COMMAND_FIELDS, "command_kwargs")
        return await self._workload(
            workload,
            lambda query: self.explain(query, query_kwargs=inner, command_kwargs=outer),
        )

    async def profile_workload(
        self,
        workload: Workload,
        *,
        verbosity: ProfileVerbosity = "executionStats",
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Profile entries with run_workload's concurrency and failure policy.

        Validate verbosity, query types and reserved options before issuing operations.
        Results contain raw diagnostics, without automatic parsing or query documents.
        """
        self._profile_verbosity(verbosity)
        inner = _options(query_kwargs, _QUERY_FIELDS, "query_kwargs")
        outer = _options(command_kwargs, _COMMAND_FIELDS, "command_kwargs")
        return await self._workload(
            workload,
            lambda query: self.profile(
                query, verbosity=verbosity, query_kwargs=inner, command_kwargs=outer
            ),
        )

    async def _workload(
        self, workload: Workload, operation: Callable[[MongoQuery], Awaitable[ExecutionResult]]
    ) -> list[ExecutionResult | None]:
        self._check_open()
        if not isinstance(workload, Workload):
            raise TypeError("workload must be a Workload")
        workload.validate()
        for entry in workload:
            self._validate_query(entry.query)
        results: list[ExecutionResult | None] = [None] * len(workload)
        next_index = 0
        stopped = False

        async def worker():
            nonlocal next_index, stopped
            while not stopped and next_index < len(workload):
                index = next_index
                next_index += 1  # No await between checking and claiming an entry.
                start = perf_counter()
                try:
                    results[index] = await operation(workload[index].query)
                except _OPERATION_ERRORS as error:
                    results[index] = ExecutionResult((perf_counter() - start) * 1000, error=error)
                    if not self.continue_on_error:
                        stopped = True

        workers = [
            asyncio.create_task(worker()) for _ in range(min(self.concurrency, len(workload)))
        ]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
        return results
