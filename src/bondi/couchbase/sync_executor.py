"""Synchronous couchbase execution through the async implementation."""

from collections.abc import Mapping
from typing import Any, Self

from bondi._callbacks import _SyncResultCallback
from bondi._sync import _SyncExecutor
from bondi.couchbase.executor import AsyncCouchbaseExecutor
from bondi.couchbase.query import CouchbaseQuery
from bondi.execution import ExecutionResult
from bondi.workload import Workload


class CouchbaseExecutor(_SyncExecutor):
    """Synchronous database executor with an owned connection.

    Create with from_uri(). Use with or explicitly call close() when finished.
    Calls retain one private event loop and must stay on the creating thread.
    Works in notebooks: the owned event loop runs on a dedicated background thread.
    Operation options, results, concurrency and errors match the async executor.
    Workload on_result callbacks run serially on the calling thread. Only regular
    callbacks are accepted; returning an awaitable raises TypeError. Do not call
    this same executor from a callback (RuntimeError). Callbacks share the async
    API's ordering, backpressure, result identity and failure/cleanup policy.
    """

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        username: str,
        password: str,
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
        health_check_timeout_seconds: float | None = None,
        cluster_kwargs: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an owned connection on a private event loop.

        Accepts the same connection options as the async executor.
        Close explicitly or use a with block.
        """

        async def connect():
            return await AsyncCouchbaseExecutor.from_uri(
                uri,
                username=username,
                password=password,
                concurrency=concurrency,
                continue_on_error=continue_on_error,
                timeout_seconds=timeout_seconds,
                health_check_timeout_seconds=health_check_timeout_seconds,
                cluster_kwargs=cluster_kwargs,
            )

        return cls._create(connect)

    def ping(self, *, timeout_seconds: float = 5) -> None:
        """Synchronously probe; options and errors match AsyncCouchbaseExecutor.ping."""
        return self._call("ping", timeout_seconds=timeout_seconds)

    def run(
        self,
        query: CouchbaseQuery,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Synchronously run; options match AsyncCouchbaseExecutor.run."""
        return self._call("run", query, collect_results=collect_results, query_kwargs=query_kwargs)

    def explain(
        self, query: CouchbaseQuery, *, query_kwargs: Mapping[str, Any] | None = None
    ) -> ExecutionResult:
        """Synchronously explain; options match AsyncCouchbaseExecutor.explain."""
        return self._call("explain", query, query_kwargs=query_kwargs)

    def profile(
        self,
        query: CouchbaseQuery,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Synchronously profile; options match AsyncCouchbaseExecutor.profile."""
        return self._call(
            "profile", query, collect_results=collect_results, query_kwargs=query_kwargs
        )

    def run_workload(
        self,
        workload: Workload,
        *,
        on_result: _SyncResultCallback | None = None,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously run workload with serialized caller-thread callbacks.

        on_result(position, entry, result) must be a regular callable returning None.
        Other options and failure behavior match AsyncCouchbaseExecutor.run_workload.
        Do not reenter this executor from a callback.
        """
        return self._call_workload(
            "run_workload",
            workload,
            collect_results=collect_results,
            query_kwargs=query_kwargs,
            on_result=on_result,
        )

    def explain_workload(
        self,
        workload: Workload,
        *,
        on_result: _SyncResultCallback | None = None,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously explain workload with serialized caller-thread callbacks.

        on_result(position, entry, result) must be a regular callable returning None.
        Other options and failure behavior match AsyncCouchbaseExecutor.explain_workload.
        Do not reenter this executor from a callback.
        """
        return self._call_workload(
            "explain_workload", workload, query_kwargs=query_kwargs, on_result=on_result
        )

    def profile_workload(
        self,
        workload: Workload,
        *,
        on_result: _SyncResultCallback | None = None,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously profile workload with serialized caller-thread callbacks.

        on_result(position, entry, result) must be a regular callable returning None.
        Other options and failure behavior match AsyncCouchbaseExecutor.profile_workload.
        Do not reenter this executor from a callback.
        """
        return self._call_workload(
            "profile_workload",
            workload,
            collect_results=collect_results,
            query_kwargs=query_kwargs,
            on_result=on_result,
        )
