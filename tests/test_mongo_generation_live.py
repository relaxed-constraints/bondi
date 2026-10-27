"""Opt-in notebook-style generation with Docker MongoDB and owned temporary samples."""

import asyncio
import os

import pytest
from pymongo import MongoClient

from dbrtoolkit.mongodb import (
    MongoCollectionRef,
    MongoExecutor,
    MongoFindQuery,
    MongoGenerationConfig,
    MongoSampleEstimator,
    MongoWorkloadGenerator,
)
from dbrtoolkit.schema import Schema


@pytest.mark.skipif(os.getenv("DBRTOOLKIT_GENERATION_LIVE") != "1", reason="opt-in Docker test")
def test_generation_live(tmp_path):
    async def notebook():
        target = MongoCollectionRef("demo", "business")
        config = MongoGenerationConfig(
            min_predicates=1,
            max_predicates=2,
            include_fields=["city", "stars", "review_count"],
            projection_probability=0.5,
        )
        with MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000) as client:
            before = list(client.demo.business.find().sort("_id", 1))
            assert len(before) >= 4, "Initialize the Docker demo collection first"
            with MongoExecutor.from_uri(
                "mongodb://localhost:27017", concurrency=4, timeout_seconds=10
            ) as executor:
                docs = executor.run(MongoFindQuery(target, {}), collect_results=True).documents
                with MongoSampleEstimator(
                    executor, target, sample_size=4, persist=True
                ) as estimator:
                    sample = estimator.sample_target
                    assert sample is not None
                    gen = MongoWorkloadGenerator(
                        target=target,
                        schema=Schema.from_documents(docs, values="full"),
                        estimator=estimator,
                        config=config,
                    )
                    w, p = gen.generate(
                        num_patterns=10,
                        instances_per_pattern=50,
                        seed=42,
                        min_selectivity=0.25,
                        max_selectivity=0.75,
                        return_patterns=True,
                    )
                    assert len(w) == 500 and len(p) == 10
                    for entry in w:
                        assert p[entry.pattern_id].matches(entry.query)
                        # Independent native verification of EVERY accepted filter on its sample.
                        matches = client[sample.database][sample.collection].count_documents(
                            entry.query.filter
                        )
                        assert 0.25 <= matches / estimator.sample_size <= 0.75
                    outcomes = executor.run_workload(w)
                    assert all(r is not None and r.error is None for r in outcomes)
                    again = gen.generate(
                        num_patterns=10,
                        instances_per_pattern=50,
                        seed=42,
                        min_selectivity=0.25,
                        max_selectivity=0.75,
                    )
                    assert [e.query.fingerprint() for e in again] == [
                        e.query.fingerprint() for e in w
                    ]
                    w.save(tmp_path / "generated.jsonl")
                assert sample.collection not in client[sample.database].list_collection_names()
            assert list(client.demo.business.find().sort("_id", 1)) == before

    asyncio.run(notebook())
