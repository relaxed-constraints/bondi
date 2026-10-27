"""Estimator contracts with scripted MongoDB responses."""

import asyncio
from types import SimpleNamespace

import pytest

from dbrtoolkit.estimation import CardinalityEstimate
from dbrtoolkit.mongodb import (
    AsyncMongoExecutor,
    AsyncMongoSampleEstimator,
    MongoAggregateQuery,
    MongoCollectionRef,
    MongoExecutor,
    MongoFindQuery,
    MongoSampleEstimator,
)

TARGET = MongoCollectionRef("source", "items")
QUERY = MongoFindQuery(TARGET, {"x": 1}, skip=2, limit=1)


class FakeExecutor(AsyncMongoExecutor):
    def __init__(self, responses):
        super().__init__(self)
        self.responses = list(responses)
        self.calls = []
        self.dropped = []

    def __getitem__(self, key):
        return self

    async def drop_collection(self, name):
        self.dropped.append(name)

    async def run(self, query, **kwargs):
        self.calls.append(query)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(documents=response)


def test_fresh_sample_actual_denominator_and_query_scope():
    async def run():
        ex = FakeExecutor(
            [[{"count": 100}], [{"sample": [{"count": 8}], "matches": [{"count": 2}]}]]
        )
        estimator = AsyncMongoSampleEstimator(ex, TARGET, sample_size=10)
        assert estimator.sample_size is None
        with pytest.raises(RuntimeError, match="prepare"):
            await estimator.estimate(QUERY)
        async with estimator:
            await estimator.prepare()  # no repeated population count
            result = await estimator.estimate(QUERY)
            assert result == CardinalityEstimate(25.0, 100, 2, 8)
            assert result.selectivity == 0.25
            pipeline = ex.calls[-1].pipeline
            assert pipeline[0] == {"$sample": {"size": 10}}
            assert pipeline[1]["$facet"]["matches"][0] == {"$match": {"x": 1}}
            assert estimator.sample_target is None
        assert not ex._closed
        with pytest.raises(RuntimeError, match="closed"):
            await estimator.estimate(QUERY)

    asyncio.run(run())


def test_persisted_count_and_cleanup():
    async def run():
        ex = FakeExecutor([[{"count": 100}], [], [{"count": 9}], [{"count": 3}]])
        async with AsyncMongoSampleEstimator(ex, TARGET, sample_size=10, persist=True) as est:
            target = est.sample_target
            assert target.database == "dbrtoolkit_samples"
            assert target != TARGET
            assert est.sample_size == 9
            result = await est.estimate(QUERY)
            assert result.cardinality == pytest.approx(100 / 3)
            assert ex.calls[-1].target == target
            assert ex.calls[-1].pipeline == [{"$match": QUERY.filter}, {"$count": "count"}]
        assert ex.dropped == [target.collection]
        await est.close()
        await est.drop_sample()
        assert len(ex.dropped) == 1

    asyncio.run(run())


def test_retained_sample_and_reprepare():
    async def run():
        ex = FakeExecutor([[{"count": 100}], [], [{"count": 10}]])
        est = AsyncMongoSampleEstimator(
            ex, TARGET, sample_size=10, persist=True, cleanup_on_exit=False
        )
        await est.prepare()
        await est.close()
        assert not ex.dropped
        assert est.sample_target
        await est.drop_sample()
        assert len(ex.dropped) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "options",
    [
        {"sample_size": 0},
        {"sample_size": True},
        {"sample_size": 1.5},
        {"sample_ratio": 0},
        {"sample_ratio": float("nan")},
        {"sample_ratio": 1.1},
        {"sample_ratio": True},
        {"sample_size": 1, "sample_ratio": 0.1},
        {"population_limit": 0},
        {"persist": 1},
        {"cleanup_on_exit": 0},
    ],
)
def test_bad_options(options):
    with pytest.raises((TypeError, ValueError)):
        AsyncMongoSampleEstimator(FakeExecutor([]), TARGET, **options)


@pytest.mark.parametrize(
    "options,size", [({"sample_size": 200}, 100), ({"sample_ratio": 0.0001}, 1)]
)
def test_adjustment_warnings(options, size):
    async def run():
        est = AsyncMongoSampleEstimator(FakeExecutor([[{"count": 100}]]), TARGET, **options)
        with pytest.warns(UserWarning):
            await est.prepare()
        assert est.sample_size == size
        await est.close()

    asyncio.run(run())


def test_empty_population_and_full_mode():
    async def run():
        for count in (0, 10):
            responses = [[{"count": count}]] if count else [[]]
            if count:
                responses.append([{"sample": [{"count": 10}], "matches": []}])
            ex = FakeExecutor(responses)
            async with AsyncMongoSampleEstimator(ex, TARGET, persist=True) as est:
                result = await est.estimate(QUERY)
                assert result.cardinality == result.selectivity == 0
                assert result.sample_size == count
                assert est.sample_target is None
                assert all("$sample" not in stage for q in ex.calls for stage in q.pipeline)

    asyncio.run(run())


def test_population_limit_and_query_validation():
    async def run():
        ex = FakeExecutor([[{"count": 20}], [{"sample": [{"count": 5}], "matches": []}]])
        async with AsyncMongoSampleEstimator(
            ex, TARGET, population_limit=20, sample_ratio=0.25
        ) as est:
            with pytest.raises(TypeError):
                await est.estimate(MongoAggregateQuery(TARGET, []))
            with pytest.raises(ValueError, match="target"):
                await est.estimate(MongoFindQuery(MongoCollectionRef("other", "items"), {}))
            await est.estimate(QUERY)
        assert all(q.pipeline[0] == {"$limit": 20} for q in ex.calls)
        assert ex.calls[-1].pipeline[1] == {"$sample": {"size": 5}}

    asyncio.run(run())


def test_creation_failure_cleanup_and_estimate_failure_context():
    async def run():
        ex = FakeExecutor([[{"count": 100}], ValueError("creation failed")])
        est = AsyncMongoSampleEstimator(
            ex, TARGET, sample_size=10, persist=True, cleanup_on_exit=False
        )
        with pytest.raises(ValueError, match="creation failed"):
            await est.prepare()
        assert len(ex.dropped) == 1
        assert est.sample_target is None
        ex = FakeExecutor([[{"count": 100}], [], [{"count": 10}], ValueError("estimate failed")])
        with pytest.raises(ValueError, match="estimate failed"):
            async with AsyncMongoSampleEstimator(ex, TARGET, sample_size=10, persist=True) as est:
                await est.estimate(QUERY)
        assert len(ex.dropped) == 1

    asyncio.run(run())


def test_sync_uses_executor_loop_and_keeps_executor_open(monkeypatch):
    loops = []

    class LoopExecutor(FakeExecutor):
        async def run(self, *args, **kwargs):
            loops.append(asyncio.get_running_loop())
            return await super().run(*args, **kwargs)

    monkeypatch.setattr(
        AsyncMongoExecutor,
        "from_uri",
        lambda *a, **kw: LoopExecutor(
            [[{"count": 10}], [{"sample": [{"count": 5}], "matches": [{"count": 2}]}]]
        ),
    )
    with MongoExecutor.from_uri("unused") as executor:
        with MongoSampleEstimator(executor, TARGET, sample_size=5) as est:
            assert est.estimate(QUERY) == CardinalityEstimate(4.0, 10, 2, 5)
        assert not executor._closed
        assert loops[0] is loops[1] is executor._runner.get_loop()
    est.close()  # already closed, even after executor shutdown


def test_drop_invalidates_preparation_and_new_sample_has_unique_name():
    async def run():
        ex = FakeExecutor(
            [
                [{"count": 100}],
                [],
                [{"count": 10}],
                [{"count": 100}],
                [],
                [{"count": 10}],
                [],
            ]
        )
        est = AsyncMongoSampleEstimator(ex, TARGET, sample_size=10, persist=True)
        await est.prepare()
        first = est.sample_target
        await est.drop_sample()
        with pytest.raises(RuntimeError, match="prepare"):
            await est.estimate(QUERY)
        await est.prepare()
        second = est.sample_target
        assert first != second
        result = await est.estimate(QUERY)
        assert result == CardinalityEstimate(0.0, 100, 0, 10)
        await est.close()
        assert ex.dropped == [first.collection, second.collection]

    asyncio.run(run())


def test_cleanup_failure_can_be_retried():
    async def run():
        ex = FakeExecutor([[{"count": 100}], [], [{"count": 10}]])
        est = AsyncMongoSampleEstimator(ex, TARGET, sample_size=10, persist=True)
        await est.prepare()
        target = est.sample_target
        original = ex.drop_collection

        async def fail(name):
            raise RuntimeError("drop failed")

        ex.drop_collection = fail
        with pytest.raises(RuntimeError, match="drop failed"):
            await est.close()
        assert est.sample_target == target
        ex.drop_collection = original
        await est.close()
        assert est.sample_target is None

    asyncio.run(run())
