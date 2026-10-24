"""Async SQL++ operations using the optional Couchbase SDK."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from datetime import timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, Self

from dbrtoolkit.couchbase.query import CouchbaseQuery
from dbrtoolkit.execution import ExecutionResult
from dbrtoolkit.workload import Workload

if TYPE_CHECKING:
    from acouchbase.cluster import Cluster


# raw could bypass these controls through native request fields. Keep this escape
# hatch closed; query_kwargs supports the SDK's named QueryOptions instead.
_RESERVED = {
    "statement",
    "named_parameters",
    "positional_parameters",
    "query_context",
    "profile",
    "metrics",
    "timeout",
    "raw",
    "serializer",
}


def _options(value: Mapping[str, Any] | None, reserved: set[str]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise TypeError("Options must be a mapping with string keys")
    conflicts = reserved.intersection(value)
    if conflicts:
        raise ValueError(f"Options override reserved fields: {', '.join(sorted(conflicts))}")
    return dict(value)


def _metadata(meta) -> dict[str, Any]:
    """Copy public SDK metadata into JSON-compatible data, without interpreting plans."""
    metrics = meta.metrics()
    return {
        "request_id": meta.request_id(),
        "client_context_id": meta.client_context_id(),
        "status": meta.status().value,
        "signature": meta.signature(),
        "warnings": [{"code": w.code(), "message": w.message()} for w in meta.warnings()],
        "profile": meta.profile(),
        "metrics": None
        if metrics is None
        else {
            "elapsed_ms": metrics.elapsed_time().total_seconds() * 1000,
            "execution_ms": metrics.execution_time().total_seconds() * 1000,
            **{
                name: getattr(metrics, name)().value
                for name in (
                    "result_count",
                    "result_size",
                    "sort_count",
                    "mutation_count",
                    "error_count",
                    "warning_count",
                )
            },
        },
    }


class AsyncCouchbaseExecutor:
    """Run, explain and profile SQL++ queries with bounded async workload workers.

    Args:
        cluster: Borrowed acouchbase Cluster; the caller closes it.
        concurrency: Positive maximum in-flight entries per workload call.
        continue_on_error: Continue scheduling after database/timeout failures.
        timeout_seconds: Positive finite per-operation deadline, including row
            consumption. None retains the SDK's configured query timeout.

    Install the couchbase extra to instantiate this class. Inputs are retained by
    reference and must not be modified during calls. Use one event loop per cluster.
    Single operations raise; workloads capture SDK operation errors. Programming
    errors and cancellation propagate. No additional retries or write guard are added.
    """

    def __init__(
        self,
        cluster: Cluster,
        *,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        try:
            import acouchbase.cluster  # noqa: F401
        except ModuleNotFoundError as error:
            if error.name not in ("acouchbase", "couchbase", "acouchbase.cluster"):
                raise
            raise ImportError(
                "Install Couchbase support with: uv sync --extra couchbase"
            ) from error
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
        self.cluster = cluster
        self.concurrency = concurrency
        self.continue_on_error = continue_on_error
        self.timeout_seconds = timeout_seconds
        self._owns_cluster = False
        self._closed = False

    @classmethod
    async def from_uri(
        cls,
        uri: str,
        *,
        username: str,
        password: str,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
        cluster_kwargs: Mapping[str, Any] | None = None,
    ) -> Self:
        """Connect an owned cluster and wait up to 30 seconds for the Query service.

        Await this factory before using async with. cluster_kwargs supplies native
        ClusterOptions; authentication comes from username/password. On readiness
        failure or cancellation the newly connected cluster is closed. Connection
        setup is outside per-query timing and uses SDK connection timeout settings.
        """
        executor = cls(
            None,
            concurrency=concurrency,
            continue_on_error=continue_on_error,
            timeout_seconds=timeout_seconds,
        )
        from acouchbase.cluster import Cluster
        from couchbase.auth import PasswordAuthenticator
        from couchbase.diagnostics import ServiceType
        from couchbase.options import ClusterOptions, WaitUntilReadyOptions

        options = _options(cluster_kwargs, {"authenticator"})
        executor.cluster = await Cluster.connect(
            uri, ClusterOptions(PasswordAuthenticator(username, password), **options)
        )
        executor._owns_cluster = True
        try:
            await executor.cluster.wait_until_ready(
                timedelta(seconds=30), WaitUntilReadyOptions(service_types=[ServiceType.Query])
            )
        except BaseException:
            await executor.close()
            raise
        return executor

    async def close(self) -> None:
        """Close an owned cluster once; leave borrowed clusters open."""
        if self._owns_cluster and not self._closed:
            await self.cluster.close()
            self._closed = True

    async def __aenter__(self) -> Self:
        self._check_open()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Executor is closed")

    def _validate_query(self, query: CouchbaseQuery) -> None:
        self._check_open()
        if not isinstance(query, CouchbaseQuery):
            raise TypeError("Expected CouchbaseQuery")
        query.validate()

    @staticmethod
    def _collect(value: bool) -> None:
        if type(value) is not bool:
            raise TypeError("collect_results must be a boolean")

    async def run(
        self,
        query: CouchbaseQuery,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Consume all rows, optionally retain them, and return metrics in raw.

        query_kwargs accepts native QueryOptions such as scan_consistency or
        read_only. Bindings, context, timeout, metrics, profile, raw and serializer
        are reserved. SDK consistency defaults apply unless explicitly overridden.
        """
        return await self._execute(query, "run", collect_results, query_kwargs)

    async def explain(
        self, query: CouchbaseQuery, *, query_kwargs: Mapping[str, Any] | None = None
    ) -> ExecutionResult:
        """Prefix the supplied statement with EXPLAIN and return its native plan in raw.

        Supply the original SQL++ statement, without an EXPLAIN prefix. No execution
        statistics are collected for that statement. row_count/documents remain None;
        EXPLAIN request metrics are not measurements of the underlying query.
        """
        return await self._execute(query, "explain", False, query_kwargs)

    async def profile(
        self,
        query: CouchbaseQuery,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute with TIMINGS profiling, consuming all rows and returning metadata.

        Unlike MongoDB profiling, Couchbase can also return the actual query rows.
        When executionTimings is absent, retain basic metrics and add a warning.
        No extra EXPLAIN request or automatic summary parsing is performed.
        """
        return await self._execute(query, "profile", collect_results, query_kwargs)

    async def _execute(
        self, query, mode: Literal["run", "explain", "profile"], collect_results, query_kwargs
    ) -> ExecutionResult:
        from couchbase.n1ql import QueryProfile
        from couchbase.options import QueryOptions

        self._validate_query(query)
        self._collect(collect_results)
        options = _options(query_kwargs, _RESERVED)
        options.update(
            named_parameters=query.named_parameters,
            positional_parameters=query.positional_parameters,
            query_context=query.query_context,
            metrics=True,
            profile=QueryProfile.TIMINGS if mode == "profile" else QueryProfile.OFF,
        )
        if self.timeout_seconds is not None:
            options["timeout"] = timedelta(seconds=self.timeout_seconds)
        statement = "EXPLAIN " + query.statement if mode == "explain" else query.statement
        rows = [] if collect_results or mode == "explain" else None
        count = 0
        start = perf_counter()
        # SDK cancellation finalizes its async streaming iterator. A local deadline
        # also bounds time spent consuming rows; the SDK timeout bounds server work.
        async with asyncio.timeout(self.timeout_seconds):
            response = self.cluster.query(statement, QueryOptions(**options))
            async for row in response.rows():
                count += 1
                if rows is not None:
                    rows.append(row)
            raw = _metadata(response.metadata())
        warnings = tuple(f"{w['code']}: {w['message']}" for w in raw["warnings"])
        if mode == "profile" and not (raw["profile"] or {}).get("executionTimings"):
            warnings += (
                "Detailed profiling unavailable: server did not return executionTimings. "
                "Basic metrics are retained; detailed profiling requires Enterprise support.",
            )
        if mode == "explain":
            if len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError("Expected one plan document from Couchbase EXPLAIN")
            raw = rows[0]
        return ExecutionResult(
            (perf_counter() - start) * 1000,
            row_count=None if mode == "explain" else count,
            documents=rows if collect_results else None,
            raw=raw,
            warnings=warnings,
        )

    async def run_workload(
        self,
        workload: Workload,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Run entries with input-aligned results and bounded concurrency.

        None marks unstarted entries. With continue_on_error=False, stop scheduling
        after observing a failure and drain in-flight operations. True attempts all
        entries. Partial rows are discarded on failure. Validate all inputs first.
        """
        self._collect(collect_results)
        options = _options(query_kwargs, _RESERVED)
        return await self._workload(
            workload,
            lambda query: self.run(query, collect_results=collect_results, query_kwargs=options),
        )

    async def explain_workload(
        self, workload: Workload, *, query_kwargs: Mapping[str, Any] | None = None
    ) -> list[ExecutionResult | None]:
        """Explain entries with run_workload's scheduling and failure policy."""
        options = _options(query_kwargs, _RESERVED)
        return await self._workload(
            workload, lambda query: self.explain(query, query_kwargs=options)
        )

    async def profile_workload(
        self,
        workload: Workload,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Profile entries with run_workload's scheduling and failure policy."""
        self._collect(collect_results)
        options = _options(query_kwargs, _RESERVED)
        return await self._workload(
            workload,
            lambda query: self.profile(
                query, collect_results=collect_results, query_kwargs=options
            ),
        )

    async def _workload(self, workload, operation) -> list[ExecutionResult | None]:
        from couchbase.exceptions import (
            AlreadyQueriedException,
            CouchbaseException,
            InvalidArgumentException,
            InvalidValueException,
        )

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
                next_index += 1
                start = perf_counter()
                try:
                    results[index] = await operation(workload[index].query)
                except (InvalidArgumentException, InvalidValueException, AlreadyQueriedException):
                    raise  # Invalid SDK options are API misuse, not database outcomes.
                except (CouchbaseException, TimeoutError) as error:
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
