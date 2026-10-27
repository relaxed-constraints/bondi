"""Synchronous mongodb execution through the async implementation."""

from collections.abc import Mapping
from typing import Any, Self

from bondi._sync import _SyncExecutor
from bondi.execution import ExecutionResult
from bondi.mongodb.executor import AsyncMongoExecutor, MongoQuery, ProfileVerbosity
from bondi.workload import Workload


class MongoExecutor(_SyncExecutor):
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
        concurrency: int = 1,
        continue_on_error: bool = False,
        timeout_seconds: float | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an owned connection on a private event loop.

        Accepts the same connection options as the async executor.
        Close explicitly or use a with block.
        """

        async def connect():
            return AsyncMongoExecutor.from_uri(
                uri,
                concurrency=concurrency,
                continue_on_error=continue_on_error,
                timeout_seconds=timeout_seconds,
                client_kwargs=client_kwargs,
            )

        return cls._create(connect)

    def run(
        self,
        query: MongoQuery,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Synchronously run; options match AsyncMongoExecutor.run."""
        return self._call("run", query, collect_results=collect_results, query_kwargs=query_kwargs)

    def explain(
        self,
        query: MongoQuery,
        *,
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Synchronously explain; options match AsyncMongoExecutor.explain."""
        return self._call(
            "explain", query, query_kwargs=query_kwargs, command_kwargs=command_kwargs
        )

    def profile(
        self,
        query: MongoQuery,
        *,
        verbosity: ProfileVerbosity = "executionStats",
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """Synchronously profile; options match AsyncMongoExecutor.profile."""
        return self._call(
            "profile",
            query,
            verbosity=verbosity,
            query_kwargs=query_kwargs,
            command_kwargs=command_kwargs,
        )

    def run_workload(
        self,
        workload: Workload,
        *,
        collect_results: bool = False,
        query_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously run workload; options match AsyncMongoExecutor.run_workload."""
        return self._call(
            "run_workload", workload, collect_results=collect_results, query_kwargs=query_kwargs
        )

    def explain_workload(
        self,
        workload: Workload,
        *,
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously explain workload; options match AsyncMongoExecutor.explain_workload."""
        return self._call(
            "explain_workload", workload, query_kwargs=query_kwargs, command_kwargs=command_kwargs
        )

    def profile_workload(
        self,
        workload: Workload,
        *,
        verbosity: ProfileVerbosity = "executionStats",
        query_kwargs: Mapping[str, Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
    ) -> list[ExecutionResult | None]:
        """Synchronously profile workload; options match AsyncMongoExecutor.profile_workload."""
        return self._call(
            "profile_workload",
            workload,
            verbosity=verbosity,
            query_kwargs=query_kwargs,
            command_kwargs=command_kwargs,
        )
