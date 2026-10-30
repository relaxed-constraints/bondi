# Quickstart

Below are example code snippets of common workflows with BONDI. Follow the
[installation guide](installation.md) first. 

Run the snippets in order in a notebook or Python script. 

## 1. Deploy a local MongoDB instance

_Requires Docker running._

Create a local MongoDB deployment and load eight fictional businesses into `demo.business`:

```python
from bondi.deployment import deploy_mongodb

deployment = deploy_mongodb()
deployment.load_demo_data()
```

The defaults use deployment name `mongodb` and port `27017`; pass `port=<port>`
to deploy on `<port>` instead. The deployment keeps running after Python exits.

API reference: [`deploy_mongodb()`](reference/deployment.md#bondi.deployment.deploy_mongodb)
and [`Deployment.load_demo_data()`](reference/deployment.md#bondi.deployment.Deployment.load_demo_data). See also [`deploy_couchbase()`](reference/deployment.md#bondi.deployment.deploy_couchbase) for deploying a local Couchbase instance.


## 2. Run a workload

_Assumes `deployment` from section 1._

Build three queries and collect their results:

```python
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

business = MongoCollectionRef("demo", "business")
workload = Workload([
    WorkloadEntry(MongoFindQuery(business, {"city": "Sydney"}, limit=1)),
    WorkloadEntry(MongoFindQuery(business, {"stars": {"$gte": 4.5}})),
    WorkloadEntry(MongoFindQuery(business, {"categories": "Restaurant"})),
])

with MongoExecutor.from_uri(deployment.uri, continue_on_error=True) as executor:
    results = executor.run_workload(workload, collect_results=True)

for result in results:
    if result.error is not None:
        print(result.error)
    else:
        print(f"Row count: {result.row_count}, Documents: {result.documents}")
```

Output (illustrative):
```text
Row count: 1, Documents: [{'_id': 'demo-001', 'business_id': 'demo-001', 'name': 'Harbour Cafe', 'city': 'Sydney', 'stars': 4.5, 'review_count': 120, 'categories': ['Cafe', 'Breakfast']}]
Row count: 3, Documents: [{'_id': 'demo-001', 'business_id': 'demo-001', 'name': 'Harbour Cafe', 'city': 'Sydney', 'stars': 4.5, 'review_count': 120, 'categories': ['Cafe', 'Breakfast']}, {'_id': 'demo-004', 'business_id': 'demo-004', 'name': 'Laneway Coffee', 'city': 'Melbourne', 'stars': 4.5, 'review_count': 200, 'categories': ['Cafe']}, {'_id': 'demo-006', 'business_id': 'demo-006', 'name': 'Market Bakery', 'city': 'Melbourne', 'stars': 5.0, 'review_count': 95, 'categories': ['Bakery']}]
Row count: 2, Documents: [{'_id': 'demo-003', 'business_id': 'demo-003', 'name': 'Station Noodles', 'city': 'Sydney', 'stars': 3.5, 'review_count': 80, 'categories': ['Restaurant']}, {'_id': 'demo-008', 'business_id': 'demo-008', 'name': 'Sunset Pizza', 'city': 'Brisbane', 'stars': 3.0, 'review_count': 70, 'categories': ['Restaurant']}]
```

On the demo dataset, the queries return 1 (limit), 3 and 2 rows. `collect_results=True` retains documents; 
omit it when only counts and timing are needed. The context manager closes the executor's connections
automatically. `continue_on_error=True` lets the remaining queries run if one fails.

API reference: [`MongoFindQuery`](reference/mongodb/queries.md#bondi.mongodb.MongoFindQuery),
[`Workload`](reference/queries.md#bondi.workload.Workload), [`WorkloadEntry`](reference/queries.md#bondi.workload.WorkloadEntry),
[`MongoExecutor`](reference/mongodb/executors.md#bondi.mongodb.MongoExecutor), and
[`ExecutionResult`](reference/results.md#bondi.execution.ExecutionResult). See also [`MongoExecutor.run()`](reference/mongodb/executors.md#bondi.mongodb.MongoExecutor.run) for executing single queries directly. 

## 3. Explain and profile queries

_Assumes `deployment` from section 1._

The executor's `.explain()` method requests the query plan without full execution statistics, using MongoDB's `explain` command with default `queryPlanner` verbosity. `.profile()` executes the query through MongoDB's `explain` command with `executionStats` verbosity.

Use the `summarize()` helper function to extract structured `QuerySummary` objects from the raw response:

```python
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery, summarize

query = MongoFindQuery(MongoCollectionRef("demo", "business"), {"city": "Sydney"})

with MongoExecutor.from_uri(deployment.uri) as executor:
    plan = summarize(executor.explain(query).raw)
    profile = summarize(executor.profile(query).raw)
    print(plan.plan_stages)
    print(
        f"Rows returned: {profile.rows_returned}, "
        f"Documents examined: {profile.documents_examined}, "
        f"Server-side execution time: {profile.execution_time_ms}ms"
    )
```

Output (illustrative):
```text
('COLLSCAN',)
Rows returned: 3, Documents examined: 8, Server-side execution time: 0.0ms
```

Planner-only explains have no execution timings. Profiling is diagnostic work;
its server execution time differs from the client's `ExecutionResult.elapsed_ms`.

API reference: [`MongoExecutor`](reference/mongodb/executors.md#bondi.mongodb.MongoExecutor),
[`summarize()`](reference/mongodb/summaries.md#bondi.mongodb.summarize), and
[`QuerySummary`](reference/results.md#bondi.summary.QuerySummary). See also [`MongoExecutor.explain_workload()`](reference/mongodb/executors.md#bondi.mongodb.MongoExecutor.explain_workload) and [`MongoExecutor.profile_workload()`](reference/mongodb/executors.md#bondi.mongodb.MongoExecutor.profile_workload) to explain and profile entire workloads. 

## 4. Analyse a schema of documents

Pass ordinary Python dictionaries to inspect field types and missing values. These could come from a query result, a parsed JSON file or any other source of semi-structured data.

```python
from bondi.schema import Schema

schema = Schema.from_documents([
    {"city": "Sydney", "stars": 4.5},
    {"city": "Melbourne", "stars": None},
    {"city": "Brisbane"},
])

print(f"Total count: {schema.document_count}")
print(f"Docs with `stars` field: {schema['stars'].count}")
print(f"Docs missing `stars`: {schema['stars'].missing_count}")
print(f"Types found for `stars`: {list(schema['stars'].types)}")
```

Output:
```text
Total count: 3
Docs with `stars` field: 2
Docs missing `stars`: 1
Types found for `stars`: ['float', 'null']
```

`null` is a present value (in Python represented as `None`), distinct from a missing field.

API reference: [`Schema`](reference/schema.md#bondi.schema.Schema) and its field/type
statistics on the same page.

## 5. Estimate cardinality

_Assumes `deployment` from section 1._ 

Cardinality estimation determines _approximately_ how many documents 
match a filter using a small sample of the data:

```python
from bondi.mongodb import (
    MongoSampleEstimator, MongoCollectionRef, MongoExecutor, MongoFindQuery
)

business = MongoCollectionRef("demo", "business")

with MongoExecutor.from_uri(deployment.uri) as executor:
    with MongoSampleEstimator(executor, business, sample_size=4) as estimator:
        
        # how many documents have city "Sydney", based on a 4-doc sample
        estimate = estimator.estimate(MongoFindQuery(business, {"city": "Sydney"}))
        
        # cardinality represents an absolute number
        print(f"Cardinality: {estimate.cardinality}")

        # selectivity is the fraction of the total documents
        print(f"Selectivity: {estimate.selectivity}")
```

Output (illustrative):

```text
Cardinality: 4.0 
Selectivity: 0.5
```

The output is probabilistic and depends on the sample drawn from the collection. 

The four-document sample is only for this tiny demo. For real datasets, choose a larger
sample based on the accuracy needed; small samples can miss rare matches.

To get exact results, omit `sample_size` to evaluate the full population, which gives cardinality 3
and selectivity 0.375 on the demo data. Cardinality counts matches before any query limit, skip or projection.

API reference:
[`MongoSampleEstimator`](reference/mongodb/estimation.md#bondi.mongodb.MongoSampleEstimator)
and [estimation results](reference/estimation.md).

## 6. Generate a random workload

_Assumes `deployment` from section 1._

BONDI contains a `MongoWorkloadGenerator` for generating random MongoDB query workloads, 
configurable through various parameters and constraints. It requires a schema (see section 4 above)
to understand the fields and values of the collection. 

In this example, we allow a maximum of two predicates per query and generate three distinct query
patterns with two instances each:

```python
from bondi.mongodb import (
    MongoCollectionRef,
    MongoExecutor,
    MongoFindQuery,
    MongoGenerationConfig,
    MongoWorkloadGenerator,
)
from bondi.schema import Schema

# read the demo.business collection and parse its schema
business = MongoCollectionRef("demo", "business")
with MongoExecutor.from_uri(deployment.uri) as executor:
    result = executor.run(MongoFindQuery(business, {}), collect_results=True)

schema = Schema.from_documents(result.documents, values="distinct")

# create the workload generator with the target collection and schema
generator = MongoWorkloadGenerator(
    target=business, schema=schema, config=MongoGenerationConfig(max_predicates=2)
)
workload, patterns = generator.generate(
    num_patterns=3, instances_per_pattern=2, return_patterns=True, seed=33
)

print(f"\nNumber of patterns: {len(patterns)}")  # 3
for pattern in patterns:
    print(pattern)

print(f"\nNumber of workload entries: {len(workload)}")  # 6
for entry in workload:
    print(f"Pattern ID: {entry.pattern_id}, Filter: {entry.query.filter}")
```

Output (illustrative):

```text
Number of patterns: 3
demo.business: stars $gte <float>
demo.business: categories $lte <str> AND name $in <2 × str>
demo.business: name $eq <str> AND review_count $gt <int> | limit=24

Number of workload entries: 6
Pattern ID: 0, Filter: {'stars': {'$gte': 5.0}}
Pattern ID: 2, Filter: {'name': 'Harbour Cafe', 'review_count': {'$gt': 120}}
Pattern ID: 1, Filter: {'categories': {'$lte': 'Restaurant'}, 'name': {'$in': ['Garden Books', 'Hilltop Deli']}}
Pattern ID: 0, Filter: {'stars': {'$gte': 5.0}}
Pattern ID: 2, Filter: {'name': 'River Bikes', 'review_count': {'$gt': 80}}
Pattern ID: 1, Filter: {'name': {'$in': ['Station Noodles', 'Sunset Pizza']}, 'categories': {'$lte': 'Cafe'}}
```
 
A fixed seed makes generation reproducible when the input data and its order are unchanged. 

Patterns have distinct shapes, instances vary their filter values and may repeat.

API reference:
[`MongoWorkloadGenerator`](reference/mongodb/generation.md#bondi.mongodb.MongoWorkloadGenerator),
[`MongoGenerationConfig`](reference/mongodb/generation.md#bondi.mongodb.MongoGenerationConfig),
[`Schema`](reference/schema.md#bondi.schema.Schema), and
[`Workload`](reference/queries.md#bondi.workload.Workload).
