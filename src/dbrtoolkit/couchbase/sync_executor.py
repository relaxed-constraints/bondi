"""Synchronous couchbase execution through the async implementation."""

from collections.abc import Mapping
from typing import Any, Self

from dbrtoolkit._sync import _SyncExecutor
from dbrtoolkit.couchbase.executor import AsyncCouchbaseExecutor
from dbrtoolkit.couchbase.query import CouchbaseQuery
from dbrtoolkit.execution import ExecutionResult
from dbrtoolkit.workload import Workload


class CouchbaseExecutor(_SyncExecutor):
    """Synchronous database executor with an owned connection.

    Create with from_uri(). Use with or explicitly call close() when finished.
    Calls retain one private event loop and must stay on the creating thread.
    Works in notebooks: the owned event loop runs on a dedicated background thread.
    Operation options, results, concurrency and errors match the async executor.
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
                cluster_kwargs=cluster_kwargs,
            )

        return cls._create(connect)

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
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously run workload; options match AsyncCouchbaseExecutor.run_workload."""
        return self._call(
            "run_workload", workload, collect_results=collect_results, query_kwargs=query_kwargs
        )

    def explain_workload(
        self, workload: Workload, *, query_kwargs: Mapping[str, Any] | None = None
    ) -> list[ExecutionResult | None]:
        """Synchronously explain workload; options match AsyncCouchbaseExecutor.explain_workload."""
        return self._call("explain_workload", workload, query_kwargs=query_kwargs)

    def profile_workload(
        self,
        workload: Workload,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously profile workload; options match AsyncCouchbaseExecutor.profile_workload."""
        return self._call(
            "profile_workload", workload, collect_results=collect_results, query_kwargs=query_kwargs
        )
