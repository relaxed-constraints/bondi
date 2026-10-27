# MongoDB sampling estimates

Estimate the number of documents matching a find filter using MongoDB's own
matching semantics. Sort, projection, skip and limit do not affect the estimate.
The query must target the estimator's source collection. Aggregation queries are
not accepted; filters must be valid in an aggregation `$match` stage.

## A reusable sample

```python
from dbrtoolkit.mongodb import (
    MongoCollectionRef, MongoExecutor, MongoSampleEstimator, MongoFindQuery,
)

target = MongoCollectionRef("demo", "business")
query = MongoFindQuery(target, {"stars": {"$gte": 4}})
with MongoExecutor.from_uri("mongodb://localhost:27017") as executor:
    with MongoSampleEstimator(
        executor, target, sample_size=4, persist=True,
    ) as estimator:
        estimate = estimator.estimate(query)
        print(estimate.cardinality, estimate.selectivity)
        print(estimate.sample_matches, estimate.sample_size)
        print(estimator.sample_target)
```

Preparation counts the population once and creates a uniquely named collection
in `dbrtoolkit_samples`. Estimates run `$match` and `$count` on that collection.
The estimator drops its own collection on exit and leaves the borrowed executor
open. The database user needs permission to create, populate and drop samples.
Source documents are not modified.

Explicit lifecycle management is also supported:

```python
estimator = MongoSampleEstimator(executor, target, sample_ratio=0.25, persist=True)
try:
    estimator.prepare()
    estimate = estimator.estimate(query)
finally:
    estimator.close()
```

Keep the executor open until estimator cleanup finishes. `prepare()` is idempotent;
`close()` is idempotent and ends use of the estimator. Constructor calls do no I/O.
Use `cleanup_on_exit=False` to retain a sample; call `drop_sample()` explicitly,
even after estimator close, while the executor is still open. Dropping a sample
before close invalidates preparation; prepare again to create a new sample.
Process termination can leave collections behind: `sample_target` identifies the
collection to remove. These are ordinary collections, not server-expiring objects.

## Fresh samples and full-population evaluation

With `persist=False` (default), each estimate draws a fresh `$sample` from the source.
A `$facet` counts all sampled documents and matching sampled documents from the
same draw. Only counts are returned to Python; records are not downloaded.

Supply either `sample_size` or `sample_ratio`, never both. Ratios must be in (0, 1];
sizes must be positive integers. Oversized requests are capped at population size
with a `UserWarning`. Ratios use Python's nearest-integer rounding; a result of zero
for a nonempty population is raised to one, with a `UserWarning`.

With neither option, or an effective size equal to the population, the estimator
evaluates the full population without creating a sample collection, even when
`persist=True`. Empty populations return zero cardinality, zero selectivity and
zero sample counts.

`population_limit=N` restricts the population to an unsorted prefix before sampling.
It changes the denominator as well as the sampled population. It is not a random
subset and should not be used as a substitute for sampling.

## Interpreting results

`CardinalityEstimate` contains estimated `cardinality` (float), recorded
`population_size`, and optional observed `sample_matches` and `sample_size`.
`selectivity` is cardinality divided by population size, or zero for an empty population.

For sampling, cardinality is `sample_matches / sample_size * population_size`.
Persisted samples use their actual count recorded at preparation. Fresh samples
report their actual count in each result; the estimator's `sample_size` property
is the effective requested size. Sample diagnostics can be absent for future
non-sampling implementations.

Zero sample matches do not prove the population has zero matches. Small samples
have coarse resolution and variable estimates. No confidence interval is provided.
Assume the source and persisted sample remain unchanged during use; preparation
and subsequent operations do not share a database snapshot. Recreate the estimator
after source changes. MongoDB sampling is not controlled by a Python random seed.

## Async notebooks

```python
from dbrtoolkit.mongodb import AsyncMongoExecutor, AsyncMongoSampleEstimator

async with AsyncMongoExecutor.from_uri("mongodb://localhost:27017") as executor:
    async with AsyncMongoSampleEstimator(
        executor, target, sample_size=4, persist=True,
    ) as estimator:
        estimate = await estimator.estimate(query)
```

Or use `await estimator.prepare()`, `await estimator.estimate(query)`, and
`await estimator.close()` across notebook cells. Do not overlap preparation or
cleanup with estimates. Executor per-operation timeouts apply; single-operation
failures propagate. A sync estimator reuses its sync executor's loop and thread.

The shared `CardinalityEstimator[QueryT]` and `AsyncCardinalityEstimator[QueryT]`
protocols live in `dbrtoolkit.estimation`. They require only `estimate(query)`;
training, preparation and sample management belong to each implementation.
Couchbase estimators and retrieval of matching examples are deferred.

See `notebooks/mongodb_estimation.ipynb` for a short Docker-backed walkthrough.
