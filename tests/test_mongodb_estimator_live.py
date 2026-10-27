"""Opt-in Docker fixture test: BONDI_ESTIMATOR_LIVE=1 uv run pytest -k estimator_live."""

import asyncio
import os

import pytest
from pymongo import MongoClient

from bondi.mongodb import (
    AsyncMongoExecutor,
    AsyncMongoSampleEstimator,
    MongoCollectionRef,
    MongoExecutor,
    MongoFindQuery,
    MongoSampleEstimator,
)


@pytest.mark.skipif(os.getenv("BONDI_ESTIMATOR_LIVE") != "1", reason="opt-in Docker test")
def test_estimator_live():
    """Read demo data; only estimator-owned sample collections are created/dropped."""
    uri = "mongodb://localhost:27017"
    target = MongoCollectionRef("demo", "business")
    query = MongoFindQuery(target, {"stars": {"$gte": 4}}, limit=1)
    with MongoClient(uri, serverSelectionTimeoutMS=3000) as client:
        count = client.demo.business.count_documents({})
        assert count > 4, "Initialize the Docker demo fixture first"
        exact = client.demo.business.count_documents(query.filter)
        owned = []
        with MongoExecutor.from_uri(uri, timeout_seconds=10) as executor:
            with MongoSampleEstimator(executor, target) as est:
                assert est.estimate(query).cardinality == exact
            for persist in (False, True):
                with MongoSampleEstimator(executor, target, sample_size=4, persist=persist) as est:
                    result = est.estimate(query)
                    assert result.sample_size == 4
                    assert 0 <= result.sample_matches <= 4
                    if persist:
                        ref = est.sample_target
                        owned.append(ref)
                        assert (
                            client[ref.database][ref.collection].count_documents(query.filter)
                            == result.sample_matches
                        )
                        assert est.estimate(query) == result

        async def run():
            async with AsyncMongoExecutor.from_uri(uri, timeout_seconds=10) as executor:
                for persist in (False, True):
                    async with AsyncMongoSampleEstimator(
                        executor,
                        target,
                        sample_ratio=0.5,
                        persist=persist,
                    ) as est:
                        if est.sample_target:
                            owned.append(est.sample_target)
                        result = await est.estimate(query)
                        assert result.population_size == count
                        assert result.sample_size == round(count * 0.5)

        asyncio.run(run())
        for ref in owned:
            assert ref.collection not in client[ref.database].list_collection_names()
        assert client.demo.business.count_documents({}) == count
