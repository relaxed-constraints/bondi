# Cardinality and selectivity estimation

Cardinality is the number of documents matching a filter. Selectivity is that
number divided by the population size, **before sort, projection, skip and limit**.
`MongoSampleEstimator` evaluates filters using MongoDB's own matching semantics.
Couchbase estimation is not implemented yet.

## Reuse a sample

```python
from dbrtoolkit.mongodb import (
    MongoCollectionRef, MongoExecutor, MongoFindQuery, MongoSampleEstimator,
)

target = MongoCollectionRef("demo", "business")
with MongoExecutor.from_uri("mongodb://127.0.0.1:27017") as executor:
    with MongoSampleEstimator(executor, target, sample_size=4, persist=True) as estimator:
        estimate = estimator.estimate(MongoFindQuery(target, {"city": "Sydney"}))
        print(estimate.cardinality, estimate.selectivity)
        print(estimate.sample_matches, estimate.sample_size)
```

The four-document sample is for the tiny demo dataset, not a research recommendation.
Choose `sample_size` or `sample_ratio`, never both. Preparation records the population
size. A persisted sample is stored in an owned collection under `dbrtoolkit_samples`
and removed on context exit; the source collection is unchanged. The database user
needs permission to create and drop the sample.

## Choose a sampling strategy

- `persist=True`: reuse one sample for repeated estimates. Useful for workload generation.
- `persist=False`: draw a fresh sample for every estimate; repeated answers can differ.
- Neither size nor ratio: evaluate the full population. No sample collection is created.

An oversized size is capped at the population size with a warning. A tiny positive
ratio rounds to at least one document for a nonempty population, also with a warning
when adjustment is needed. Samples are not controlled by the generator's Python seed.

## Interpret the result

The estimate scales sample matches to the recorded population. Zero matches in a
sample do not prove zero matches in the source. Small samples give coarse selectivity
resolution; no confidence interval is supplied. Keep the source static during an
experiment and use full-collection verification when you need a guarantee.

The estimator borrows its executor, so close the estimator before closing the
executor. Context managers enforce that order and also clean up on exceptions.
See [sampling APIs](reference/mongodb/estimation.md) for manual lifecycle management
and [estimation interfaces](reference/estimation.md) for custom research estimators.
