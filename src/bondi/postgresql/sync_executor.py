"""Synchronous postgresql execution through the async implementation."""

from typing import Self

from bondi._callbacks import _SyncResultCallback
from bondi._sync import _SyncExecutor
from bondi.connection import PostgresConnection
from bondi.execution import ExecutionResult
from bondi.load import LoadResult, Selection, SyncLoadCallback
from bondi.postgresql.executor import AsyncPostgresExecutor
from bondi.postgresql.query import PostgresQuery
from bondi.workload import Workload


class PostgresExecutor(_SyncExecutor):
    """Synchronous database executor with an owned connection.

    Create with from_connection(). Use with or explicitly call close() when finished.
    Calls retain one private event loop and must stay on the creating thread.
    Works in notebooks: the owned event loop runs on a dedicated background thread.
    Operation options, results, concurrency and errors match the async executor.
    Workload on_result callbacks run serially on the calling thread. Only regular
    callbacks are accepted; returning an awaitable raises TypeError. Do not call
    this same executor from a callback (RuntimeError). Callbacks share the async
    API's ordering, backpressure, result identity and failure/cleanup policy.
    """

    @classmethod
    def from_connection(
        cls,
        connection: PostgresConnection,
        *,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
        health_check_timeout_seconds: float | None = None,
    ) -> Self:
        """Create an owned connection on a private event loop.

        Accepts the same connection options as the async executor.
        Close explicitly or use a with block.

        Args:
            connection: PostgresConnection settings for the instance. No client is borrowed.
            concurrency: Positive maximum number of in-flight workload entries.
            continue_on_error: Schedule remaining entries after database operation errors.
            timeout_seconds: Optional positive finite deadline per query operation.
            health_check_timeout_seconds: Optional positive finite preflight deadline.

        Returns:
            A [`PostgresExecutor`][bondi.postgresql.PostgresExecutor] that owns its connection.
        """

        async def connect():
            return await AsyncPostgresExecutor.from_connection(
                connection,
                concurrency=concurrency,
                continue_on_error=continue_on_error,
                timeout_seconds=timeout_seconds,
                health_check_timeout_seconds=health_check_timeout_seconds,
            )

        return cls._create(connect)

    def ping(self, *, timeout_seconds: float = 5) -> None:
        """Synchronously probe; options and errors match AsyncPostgresExecutor.ping."""
        return self._call("ping", timeout_seconds=timeout_seconds)

    def run(
        self,
        query: PostgresQuery,
        *,
        collect_results: bool = False,
    ) -> ExecutionResult:
        """Synchronously run; options match AsyncPostgresExecutor.run.

        Returns:
            Query metrics, the row count, and documents if requested.
        """
        return self._call("run", query, collect_results=collect_results)

    def explain(self, query: PostgresQuery) -> ExecutionResult:
        """Synchronously explain; options match AsyncPostgresExecutor.explain.

        Returns:
            The native PostgreSQL execution plan in `raw`.
        """
        return self._call("explain", query)

    def profile(
        self,
        query: PostgresQuery,
    ) -> ExecutionResult:
        """Synchronously profile; options match AsyncPostgresExecutor.profile.

        Returns:
            The instrumented native JSON plan in raw.
        """
        return self._call("profile", query)

    def generate_load(
        self,
        workload: Workload,
        *,
        selection: Selection,
        measurement_seconds: float,
        drain_timeout_seconds: float,
        warmup_seconds: float = 0,
        collect_results: bool = False,
        return_load_results: bool = True,
        on_result: SyncLoadCallback | None = None,
    ) -> list[LoadResult]:
        """Run queries repeatedly, with callbacks on the calling thread.

        Args:
            workload: Nonempty workload for this executor's backend.
            selection: Per-client [WeightedRandom][bondi.load.WeightedRandom],
                [UniformRandom][bondi.load.UniformRandom],
                [Sequential][bondi.load.Sequential] or [ByPattern][bondi.load.ByPattern] policy.
            measurement_seconds: Measurement duration in seconds. Must be positive and finite.
            drain_timeout_seconds: Positive finite drain allowance; expiry produces
                unresolved observations and requests cooperative cancellation.
            warmup_seconds: Nonnegative finite warm-up duration, default zero.
            collect_results: Retain returned database documents, default False.
            return_load_results: Retain LoadResults in the returned list, default True.
            on_result: [SyncLoadCallback][bondi.load.SyncLoadCallback] receiving
                each LoadResult, including errors
                and drain expiry. Must not return an awaitable or reenter the executor.

        Inherits executor concurrency, query timeout, error policy and health checks.
        Callbacks run one at a time, even when result retention is disabled.
        Each client waits for its callback before starting another query.
        LoadResult.duration excludes callback time. Cleanup and
        callbacks may extend beyond drain expiry; no hard process deadline or
        server-side termination guarantee is provided. Programming/callback errors
        and caller interruption propagate after cleanup.

        Returns:
            LoadResults in callback-delivery order, or [] when retention is disabled.
            See the async executor method for the complete scheduling contract.
        """
        return self._call_workload(
            "generate_load",
            workload,
            selection=selection,
            measurement_seconds=measurement_seconds,
            drain_timeout_seconds=drain_timeout_seconds,
            warmup_seconds=warmup_seconds,
            collect_results=collect_results,
            return_load_results=return_load_results,
            on_result=on_result,
        )

    def run_workload(
        self,
        workload: Workload,
        *,
        on_result: _SyncResultCallback | None = None,
        collect_results: bool = False,
    ) -> list[ExecutionResult | None]:
        """Synchronously run workload with serialized caller-thread callbacks.

        on_result(position, entry, result) must be a regular callable returning None.
        Other options and failure behavior match AsyncPostgresExecutor.run_workload.
        Do not reenter this executor from a callback.

        Returns:
            Execution outcomes in workload order, with `None` for unstarted entries.
        """
        return self._call_workload(
            "run_workload",
            workload,
            collect_results=collect_results,
            on_result=on_result,
        )

    def explain_workload(
        self,
        workload: Workload,
        *,
        on_result: _SyncResultCallback | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously explain workload with serialized caller-thread callbacks.

        on_result(position, entry, result) must be a regular callable returning None.
        Other options and failure behavior match AsyncPostgresExecutor.explain_workload.
        Do not reenter this executor from a callback.

        Returns:
            Explain outcomes in workload order, with `None` for unstarted entries.
        """
        return self._call_workload("explain_workload", workload, on_result=on_result)

    def profile_workload(
        self,
        workload: Workload,
        *,
        on_result: _SyncResultCallback | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously profile workload with serialized caller-thread callbacks.

        on_result(position, entry, result) must be a regular callable returning None.
        Other options and failure behavior match AsyncPostgresExecutor.profile_workload.
        Do not reenter this executor from a callback.

        Returns:
            Profile outcomes in workload order, with `None` for unstarted entries.
        """
        return self._call_workload(
            "profile_workload",
            workload,
            on_result=on_result,
        )
