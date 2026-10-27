"""MongoDB-native filter estimation over fresh or materialized samples."""

import math
import warnings
from typing import Self
from uuid import uuid4

from dbrtoolkit.estimation import CardinalityEstimate
from dbrtoolkit.mongodb.aggregate import MongoAggregateQuery
from dbrtoolkit.mongodb.collection import MongoCollectionRef
from dbrtoolkit.mongodb.executor import AsyncMongoExecutor
from dbrtoolkit.mongodb.query import MongoFindQuery
from dbrtoolkit.mongodb.sync_executor import MongoExecutor


class AsyncMongoSampleEstimator:
    """Estimate filter cardinality using MongoDB matching semantics.

    Construction does no I/O. Call prepare() or enter an async context before
    estimating. The executor is borrowed and must outlive the estimator. Lifecycle
    operations must not overlap estimates; inputs and source data should stay stable.

    Args:
        executor: Borrowed async executor providing connection and timeouts.
        target: Source collection; estimate queries must target this collection.
        sample_size: Positive requested size, capped at population size with a warning.
        sample_ratio: Alternative fraction in (0, 1]; rounded to nearest integer,
            with a minimum of one for nonempty populations (warning when adjusted).
        persist: Materialize one reusable sample; otherwise sample anew per estimate.
        sample_database: Database for uniquely named, estimator-owned collections.
        population_limit: Optional positive prefix limit defining the population.
        cleanup_on_exit: Drop the owned sample on close/context exit. If False,
            drop_sample() remains available after close while the executor is open.

    Supplying neither size nor ratio evaluates the full population. Even with
    persist=True, full-population mode uses the source directly and creates no
    sample collection. Population size is counted once during preparation. A
    population_limit selects an unsorted prefix, not a random population.
    """

    def __init__(
        self,
        executor: AsyncMongoExecutor,
        target: MongoCollectionRef,
        *,
        sample_size: int | None = None,
        sample_ratio: float | None = None,
        persist: bool = False,
        sample_database: str = "dbrtoolkit_samples",
        population_limit: int | None = None,
        cleanup_on_exit: bool = True,
    ) -> None:
        if not isinstance(executor, AsyncMongoExecutor):
            raise TypeError("executor must be an AsyncMongoExecutor")
        if not isinstance(target, MongoCollectionRef):
            raise TypeError("target must be a MongoCollectionRef")
        if sample_size is not None and sample_ratio is not None:
            raise ValueError("Use only one of sample_size or sample_ratio")
        for name, value in (("sample_size", sample_size), ("population_limit", population_limit)):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive integer")
        if sample_ratio is not None and (
            type(sample_ratio) not in (int, float)
            or not math.isfinite(sample_ratio)
            or not 0 < sample_ratio <= 1
        ):
            raise ValueError("sample_ratio must be finite and in (0, 1]")
        if type(persist) is not bool or type(cleanup_on_exit) is not bool:
            raise TypeError("persist and cleanup_on_exit must be bool")
        MongoCollectionRef(sample_database, "validate")
        self._executor = executor
        self._target = target
        self._requested_size = sample_size
        self._ratio = sample_ratio
        self._persist = persist
        self._sample_database = sample_database
        self._limit = population_limit
        self._cleanup = cleanup_on_exit
        self._population_size: int | None = None
        self._sample_size: int | None = None
        self._sample_target: MongoCollectionRef | None = None
        self._prepared = False
        self._closed = False

    @property
    def population_size(self) -> int | None:
        """Recorded population count, or None before preparation."""
        return self._population_size

    @property
    def sample_size(self) -> int | None:
        """Effective size; actual materialized count when persisted, None before preparation."""
        return self._sample_size

    @property
    def sample_target(self) -> MongoCollectionRef | None:
        """Owned sample collection, or None when no materialized sample exists."""
        return self._sample_target

    def _prefix(self) -> list[dict]:
        return [{"$limit": self._limit}] if self._limit is not None else []

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Estimator is closed")
        self._executor._check_open()

    async def _run(self, target, pipeline):
        result = await self._executor.run(
            MongoAggregateQuery(target, pipeline), collect_results=True
        )
        return result.documents

    async def prepare(self) -> Self:
        """Count the population and optionally materialize a sample; idempotent.

        Adjustment warnings are UserWarning. Failed sample creation attempts
        cleanup even when cleanup_on_exit=False. Database errors propagate.
        """
        self._check_open()
        if self._prepared:
            return self
        if self._sample_target is not None:
            raise RuntimeError("Call drop_sample() to clean up the previous failed preparation")
        rows = await self._run(self._target, self._prefix() + [{"$count": "count"}])
        population = rows[0]["count"] if rows else 0
        size = population
        if self._requested_size is not None:
            size = min(self._requested_size, population)
            if self._requested_size > population:
                warnings.warn(
                    f"Requested sample_size={self._requested_size} exceeds "
                    f"population_size={population}; using all {population} documents.",
                    UserWarning,
                    stacklevel=2,
                )
        elif self._ratio is not None:
            size = round(population * self._ratio)
            if population and size == 0:
                size = 1
                warnings.warn(
                    f"sample_ratio={self._ratio} rounds to zero documents for "
                    f"population_size={population}; using one document.",
                    UserWarning,
                    stacklevel=2,
                )
        self._population_size = population
        self._sample_size = size
        if self._persist and 0 < size < population:
            target = MongoCollectionRef(self._sample_database, f"sample_{uuid4().hex}")
            self._sample_target = target
            try:
                # UUID names keep ownership separate from source and other estimators.
                await self._run(
                    self._target,
                    self._prefix()
                    + [
                        {"$sample": {"size": size}},
                        {"$out": {"db": target.database, "coll": target.collection}},
                    ],
                )
                rows = await self._run(target, [{"$count": "count"}])
                self._sample_size = rows[0]["count"] if rows else 0
                if not self._sample_size:
                    raise RuntimeError("Sample became empty during preparation; source changed")
            except BaseException:
                await self.drop_sample()
                raise
        self._prepared = True
        return self

    async def estimate(self, query: MongoFindQuery) -> CardinalityEstimate:
        """Estimate filter matches before sort/projection/skip/limit.

        Returns sample matches and actual evaluated sample size. Fresh samples
        use a facet so numerator and denominator describe the same draw. Source
        mutation can invalidate the recorded population; no snapshot is promised.
        """
        self._check_open()
        if not self._prepared:
            raise RuntimeError("Call prepare() or use async with before estimating")
        if not isinstance(query, MongoFindQuery):
            raise TypeError("query must be a MongoFindQuery")
        query.validate()
        if query.target != self._target:
            raise ValueError("query target must match the estimator's source collection")
        population = self._population_size
        if population == 0:
            return CardinalityEstimate(0.0, 0, 0, 0)
        if self._sample_target is not None:
            rows = await self._run(
                self._sample_target,
                [
                    {"$match": query.filter},
                    {"$count": "count"},
                ],
            )
            matches = rows[0]["count"] if rows else 0
            size = self._sample_size
        else:
            pipeline = self._prefix()
            if self._sample_size < population:
                pipeline.append({"$sample": {"size": self._sample_size}})
            pipeline.append(
                {
                    "$facet": {
                        "sample": [{"$count": "count"}],
                        "matches": [{"$match": query.filter}, {"$count": "count"}],
                    }
                }
            )
            rows = await self._run(self._target, pipeline)
            counts = rows[0] if rows else {"sample": [], "matches": []}
            size = counts["sample"][0]["count"] if counts["sample"] else 0
            matches = counts["matches"][0]["count"] if counts["matches"] else 0
            if size == 0:
                raise RuntimeError("Population became empty; prepare a new estimator")
        return CardinalityEstimate(matches / size * population, population, matches, size)

    async def drop_sample(self) -> None:
        """Drop only this estimator's sample; idempotent, including after close.

        Dropping an active sample invalidates preparation. Call prepare() again
        to create a new sample. The borrowed executor must remain open.
        """
        if self._sample_target is None:
            return
        self._executor._check_open()
        target = self._sample_target
        with self._executor._timeout():
            await self._executor.client[target.database].drop_collection(target.collection)
        self._sample_target = None
        self._prepared = False

    async def close(self) -> None:
        """Clean up the sample by default; never close the borrowed executor."""
        if self._closed:
            return
        if self._cleanup:
            await self.drop_sample()
        self._closed = True

    async def __aenter__(self) -> Self:
        return await self.prepare()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()


class MongoSampleEstimator:
    """Synchronous facade using its borrowed MongoExecutor's existing event loop.

    Options and results match AsyncMongoSampleEstimator. Use prepare()/close()
    or a with block. Close the estimator before closing its executor. No second
    connection or event loop is created.
    """

    def __init__(
        self,
        executor: MongoExecutor,
        target: MongoCollectionRef,
        *,
        sample_size: int | None = None,
        sample_ratio: float | None = None,
        persist: bool = False,
        sample_database: str = "dbrtoolkit_samples",
        population_limit: int | None = None,
        cleanup_on_exit: bool = True,
    ) -> None:
        if not isinstance(executor, MongoExecutor):
            raise TypeError("executor must be a MongoExecutor")
        executor._check()
        self._executor = executor
        self._estimator = AsyncMongoSampleEstimator(
            executor._executor,
            target,
            sample_size=sample_size,
            sample_ratio=sample_ratio,
            persist=persist,
            sample_database=sample_database,
            population_limit=population_limit,
            cleanup_on_exit=cleanup_on_exit,
        )

    @property
    def population_size(self) -> int | None:
        """Recorded population count, or None before preparation."""
        return self._estimator.population_size

    @property
    def sample_size(self) -> int | None:
        """Effective sample size, or None before preparation."""
        return self._estimator.sample_size

    @property
    def sample_target(self) -> MongoCollectionRef | None:
        """Owned sample collection, or None."""
        return self._estimator.sample_target

    def _call(self, method, *args):
        self._executor._check()

        async def invoke():
            return await getattr(self._estimator, method)(*args)

        return self._executor._runner.run(invoke())

    def prepare(self) -> Self:
        """Prepare explicitly; entering a with block also prepares."""
        self._call("prepare")
        return self

    def estimate(self, query: MongoFindQuery) -> CardinalityEstimate:
        """Estimate filter cardinality using the borrowed executor's loop."""
        return self._call("estimate", query)

    def drop_sample(self) -> None:
        """Drop the owned sample, including after close if it was retained."""
        if self.sample_target is not None:
            self._call("drop_sample")

    def close(self) -> None:
        """Close the estimator; repeated calls are harmless."""
        if not self._estimator._closed:
            self._call("close")

    def __enter__(self) -> Self:
        return self.prepare()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
