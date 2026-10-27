# BONDI — A Python toolkit for document database research

BONDI provides reusable components for students and researchers working with document databases:

- **Native queries:** describe MongoDB find/aggregation queries and Couchbase SQL++ queries.
- **Query execution:** run individual queries or workloads, with optional concurrency.
- **Explain and profiling:** inspect plans and extract common execution metrics.
- **Workload persistence:** save and reload queries with their pattern IDs.
- **Schema inspection:** explore nested fields, types, missingness and observed values.
- **Selectivity estimation:** estimate MongoDB filter cardinality using fresh or persisted samples.
- **Workload generation:** generate MongoDB find patterns with multiple instances and optional selectivity constraints.

The examples below use synchronous APIs, which work in scripts and notebooks.
Execution and summary parsing support MongoDB and Couchbase; estimation and generation
currently target MongoDB.

[Documentation](https://relaxed-constraints.github.io/bondi/) ·
[Quickstart](https://relaxed-constraints.github.io/bondi/quickstart/) ·
[API reference](https://relaxed-constraints.github.io/bondi/api/)

## Install

Requires Python **3.11+**. In a uv project:

```sh
uv add bondi
```

Or use `pip install bondi`. To execute Couchbase queries, install the optional extra:
`uv add 'bondi[couchbase]'` or `pip install 'bondi[couchbase]'`.

For notebooks, Docker Compose files and demo data, get the source from a
[GitHub release](https://github.com/relaxed-constraints/bondi/releases).
The [installation guide](https://relaxed-constraints.github.io/bondi/installation/)
explains both paths. Database examples below assume the
[local MongoDB demo](https://relaxed-constraints.github.io/bondi/local-databases/)
is initialized on port 27017; later snippets reuse earlier variables.

## Native queries

Describe operations without opening a connection. MongoDB filters and pipelines
stay native, while Couchbase queries use SQL++ text and parameters.

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery
from bondi.couchbase import CouchbaseQuery

business = MongoCollectionRef("demo", "business")
query = MongoFindQuery(business, {"city": "Sydney"}, limit=5)
sql = CouchbaseQuery(
    "SELECT RAW b FROM `demo`.`_default`.`business` b WHERE b.city = $city",
    named_parameters={"city": "Sydney"},
)
```

[MongoDB queries](https://relaxed-constraints.github.io/bondi/find-query/) ·
[Couchbase queries](https://relaxed-constraints.github.io/bondi/couchbase-query/)

## Query execution

Executors consume all rows and optionally retain them. Workload methods use the same
interface with configurable concurrency and error handling.

```python
from bondi.mongodb import MongoExecutor

with MongoExecutor.from_uri("mongodb://127.0.0.1:27017") as executor:
    result = executor.run(query, collect_results=True)
    print(result.documents)
    print(result.row_count, result.elapsed_ms)
```

[Execution guide](https://relaxed-constraints.github.io/bondi/executor/)

## Explain and profiling

Use `explain()` for a plan and `profile()` for execution diagnostics. Parse the raw
response explicitly; unavailable summary metrics remain `None`.

```python
from bondi.mongodb import summarize

with MongoExecutor.from_uri("mongodb://127.0.0.1:27017") as executor:
    result = executor.profile(query)

summary = summarize(result.raw)
print(summary.plan_stages, summary.index_names, summary.execution_time_ms)
```

[Explain and profile](https://relaxed-constraints.github.io/bondi/profiling/) ·
[Metric interpretation](https://relaxed-constraints.github.io/bondi/summaries/)

## Workload persistence

Group queries into an ordered, single-backend workload. JSONL persistence restores
concrete query objects, BSON filter values and optional pattern IDs.

```python
from bondi.workload import Workload, WorkloadEntry

workload = Workload([WorkloadEntry(query, pattern_id=0)])
workload.save("workload.jsonl")
restored = Workload.load("workload.jsonl")
```

[Queries and workloads](https://relaxed-constraints.github.io/bondi/workloads/)

## Schema inspection

Inspect Python dictionaries from either database or a file, without a database
connection. Retain distinct values when you want to generate queries later.

```python
from bondi.schema import Schema

schema = Schema.from_documents(
    [{"city": "Sydney", "stars": 4}, {"city": "Melbourne"}],
    values="distinct",
)
print(schema["stars"].missing_count)  # 1
print(schema["city"].types["str"].values)
```

[Schema inspection](https://relaxed-constraints.github.io/bondi/schemas/)

## Selectivity estimation

Estimate filter matches using MongoDB's own semantics, before skip and limit.
A persisted sample is reused across estimates and removed when its context closes.

```python
from bondi.mongodb import MongoSampleEstimator

with MongoExecutor.from_uri("mongodb://127.0.0.1:27017") as executor:
    with MongoSampleEstimator(executor, business, sample_size=4, persist=True) as estimator:
        estimate = estimator.estimate(query)
        print(estimate.cardinality, estimate.selectivity)
```

Four documents illustrate the API on the tiny demo dataset; use a representative
sample for research. Sample estimates are not full-population guarantees.
[Estimation guide](https://relaxed-constraints.github.io/bondi/mongodb-estimation/)

## Workload generation

Generate distinct flat-find patterns whose instances vary filter values. Supply a
prepared estimator to enforce sample-based selectivity bounds on each instance.

```python
from bondi.mongodb import MongoGenerationConfig, MongoWorkloadGenerator

generator = MongoWorkloadGenerator(
    target=business,
    schema=schema,
    config=MongoGenerationConfig(min_predicates=1, max_predicates=2),
)
workload = generator.generate(num_patterns=10, instances_per_pattern=50, seed=42)
print(len(workload))  # 500
```

[Generation guide](https://relaxed-constraints.github.io/bondi/workload-generation/) ·
[End-to-end tutorial](https://relaxed-constraints.github.io/bondi/tutorials/generate-workload/)

---

BONDI is maintained by **Relaxed Constraints** and distributed under the [MIT license](LICENSE).
For development, see [Contributing](https://relaxed-constraints.github.io/bondi/contributing/).
Report problems or suggest improvements through [GitHub issues](https://github.com/relaxed-constraints/bondi/issues).
