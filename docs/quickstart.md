# Quickstart

Five common workflows, using minimal Python examples. Follow the
[installation guide](installation.md) first. Deployment and demo-data loading are
currently unreleased; use a current source checkout with `uv sync` for these examples.
Run the snippets in order in a notebook or Python script. Schema analysis is
independent and needs no database.

## 1. Deploy MongoDB

Start Docker, then create a local MongoDB deployment and load eight fictional
businesses into `demo.business`:

```python
from bondi.deployment import deploy_mongodb

deployment = deploy_mongodb()
deployment.load_demo_data()
```

The defaults use deployment name `mongodb` and port `27017`; pass `port=27019`
if that port is occupied. The deployment keeps running after Python exits.
Loading again replaces the eight demo documents without duplicating them or
removing unrelated data.

API reference: [`deploy_mongodb`](reference/deployment.md#bondi.deployment.deploy_mongodb)
and [`Deployment`](reference/deployment.md#bondi.deployment.Deployment), including
`load_demo_data()`, `stop()` and `remove()`.

## 2. Run a workload

Reuse `deployment` from section 1. Build three queries and collect their results:

```python
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

business = MongoCollectionRef("demo", "business")
workload = Workload([
    WorkloadEntry(MongoFindQuery(business, {"city": "Sydney"})),
    WorkloadEntry(MongoFindQuery(business, {"stars": {"$gte": 4.5}})),
    WorkloadEntry(MongoFindQuery(business, {"categories": "Restaurant"})),
])

with MongoExecutor.from_uri(deployment.uri) as executor:
    results = executor.run_workload(workload, collect_results=True)

for result in results:
    if result is None:
        print("Not started")
    elif result.error is not None:
        print(result.error)
    else:
        print(result.row_count, result.documents)
```

Results follow workload order. On the demo dataset, the queries return 3, 3 and 2
rows. `collect_results=True` retains documents; omit it when only counts and timing
are needed. The context manager closes the executor's connections.

API reference: [`MongoFindQuery`](reference/mongodb/queries.md#bondi.mongodb.MongoFindQuery),
[`Workload` and `WorkloadEntry`](reference/queries.md),
[`MongoExecutor`](reference/mongodb/executors.md#bondi.mongodb.MongoExecutor), and
[`ExecutionResult`](reference/results.md#bondi.execution.ExecutionResult).

## 3. Explain and profile queries

Reuse `deployment` from section 1. Explain inspects a plan;
profile executes the query through MongoDB's explain-with-execution-statistics mode.
Use `summarize()` to extract comparable fields from the raw response:

```python
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery, summarize

query = MongoFindQuery(MongoCollectionRef("demo", "business"), {"city": "Sydney"})

with MongoExecutor.from_uri(deployment.uri) as executor:
    plan = summarize(executor.explain(query).raw)
    profile = summarize(executor.profile(query).raw)
    print(plan.plan_stages)
    print(profile.rows_returned, profile.documents_examined, profile.execution_time_ms)
```

Planner-only explains have no execution timings. Profiling is diagnostic work;
its server execution time differs from the client's `ExecutionResult.elapsed_ms`.

API reference: [`MongoExecutor`](reference/mongodb/executors.md#bondi.mongodb.MongoExecutor),
[`summarize`](reference/mongodb/summaries.md#bondi.mongodb.summarize), and
[`QuerySummary`](reference/results.md#bondi.summary.QuerySummary).

## 4. Analyse a schema without a database

Pass ordinary Python dictionaries to inspect field types and missing values:

```python
from bondi.schema import Schema

schema = Schema.from_documents([
    {"city": "Sydney", "stars": 4.5},
    {"city": "Melbourne", "stars": None},
    {"city": "Brisbane"},
])

print(schema.document_count)          # 3
print(schema["stars"].count)          # 2
print(schema["stars"].missing_count)  # 1
print(list(schema["stars"].types))    # ['float', 'null']
```

Null is a present value, distinct from a missing field. The schema describes only
the documents supplied; it does not impose validation rules.

API reference: [`Schema`](reference/schema.md#bondi.schema.Schema) and its field/type
statistics on the same page.

## 5. Estimate cardinality

Reuse `deployment` and `business` from sections 1–2. Estimate how many documents
match a filter using a small sample:

```python
from bondi.mongodb import MongoSampleEstimator

with MongoExecutor.from_uri(deployment.uri) as executor:
    with MongoSampleEstimator(executor, business, sample_size=4) as estimator:
        estimate = estimator.estimate(MongoFindQuery(business, {"city": "Sydney"}))
        print(estimate.cardinality, estimate.selectivity)
        print(estimate.sample_matches, estimate.sample_size)
```

The four-document sample is for this tiny demo; estimates vary between runs.
Omit `sample_size` to evaluate the full population, which gives cardinality 3
and selectivity 0.375 on the unchanged demo data. Cardinality counts matches
before any query limit, skip or projection.

API reference:
[`MongoSampleEstimator`](reference/mongodb/estimation.md#bondi.mongodb.MongoSampleEstimator)
and [estimation results](reference/estimation.md).
