"""Run with: uv run python scripts/generate_yelp_workload.py.

Saves yelp-workload.jsonl in the current directory. Selectivity is sample-based;
this example does not perform exact full-collection verification.
"""

from pymongo import MongoClient

from dbrtoolkit.mongodb import (
    MongoCollectionRef,
    MongoExecutor,
    MongoGenerationConfig,
    MongoSampleEstimator,
    MongoWorkloadGenerator,
)
from dbrtoolkit.schema import Schema

URI = "mongodb://127.0.0.1:27018/?serverSelectionTimeoutMS=5000"
TARGET = MongoCollectionRef("yelp", "business")
NUM_PATTERNS = 10


def attribute_fields(pattern):
    fields = {p.field for p in pattern.predicates}
    fields.update(field for field, _ in pattern.sort)
    fields.update(field for field, _ in pattern.projection or ())
    return {f for f in fields if f == "attributes" or f.startswith("attributes.")}


def validate_pattern(candidate, accepted):
    # At most one attribute field per pattern; at most half the patterns use one.
    fields = attribute_fields(candidate)
    return len(fields) <= 1 and (
        not fields or sum(bool(attribute_fields(p)) for p in accepted) < NUM_PATTERNS // 2
    )


def main():
    config = MongoGenerationConfig(
        min_predicates=2,
        max_predicates=5,
        exclude_fields=["_id", "business_id"],
        field_weights={"default": 1.0, "overrides": {"attributes.*": 0.05, "hours.*": 0.05}},
        sort_probability=0.5,
        sort_on_filter_field_ratio=0.5,
        sort_two_field_ratio=0.3,
        sort_ascending_ratio=0.8,
        skip_probability=0.0,
        skip_min=0,
        skip_max=20,
        skip_requires_limit=True,
        limit_probability=0.5,
        limit_min=5,
        limit_max=100,
        projection_probability=0.5,
        projection_filter_overlap_ratio=0.5,
        projection_min_fields=1,
        projection_max_fields=5,
        projection_exclude_id_ratio=0.5,
    )

    print("Reading schema from up to 200,000 documents...", flush=True)
    # Feed the cursor directly into the schema parser, without retaining every document.
    with MongoClient(URI) as client:
        with client.yelp.business.find({}).limit(200_000) as documents:
            schema = Schema.from_documents(documents, values="distinct")

    with MongoExecutor.from_uri(URI, timeout_seconds=120) as executor:
        # Only the owned temporary sample is written; it is removed on exit.
        with MongoSampleEstimator(executor, TARGET, sample_size=16_000, persist=True) as estimator:
            generator = MongoWorkloadGenerator(
                target=TARGET, schema=schema, estimator=estimator, config=config
            )
            print("Generating 10 patterns with 100 instances each...", flush=True)
            workload = generator.generate(
                num_patterns=NUM_PATTERNS,
                instances_per_pattern=100,
                min_selectivity=1e-6 + 0.0005,
                max_selectivity=1.0 - 0.0005,
                validate_pattern=validate_pattern,
                seed=42,
                max_candidate_attempts=1_000_000,
                max_instance_attempts=10_000,
                timeout_seconds=600,
            )

    workload.save("yelp-workload.jsonl")
    print(f"Saved {len(workload)} queries to yelp-workload.jsonl")


if __name__ == "__main__":
    main()
