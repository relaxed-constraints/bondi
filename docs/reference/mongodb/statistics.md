# MongoDB query statistics API

Use `query_statistics()` for offline, versioned structural counts. The
[MongoDB Query statistics guide](../../mongodb-query-statistics.md) defines every
counting rule, nested-pipeline scope, conversion behavior and supported syntax.

## Find example

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery, query_statistics

query = MongoFindQuery(MongoCollectionRef("demo", "items"), {"price": {"$gte": 10}}, limit=5)
stats = query_statistics(query)
assert (stats.stage_count, stats.predicate_count, stats.operator_count) == (2, 1, 1)
assert stats.operator_counts == {"$gte": 1}
assert stats.expression_depth == stats.filter_logical_depth == stats.filter_logical_fan_out == 0
```

## Nested aggregation example

```python
from bondi.mongodb import MongoAggregateQuery, MongoCollectionRef, query_statistics

query = MongoAggregateQuery(
    MongoCollectionRef("demo", "items"),
    [{"$facet": {"active": [{"$match": {"active": True}}, {"$count": "n"}]}}],
)
stats = query_statistics(query, include_nested_pipelines=True)
assert (stats.stage_count, stats.predicate_count, stats.operator_count) == (3, 1, 1)
assert stats.stages[1].path == (0, "$facet", "active", 0)
assert stats.nested_pipeline_depth == 1
```

## Logical structure example

```python
query = MongoFindQuery(MongoCollectionRef("demo", "items"), {"a": 1, "b": 2})
stats = query_statistics(query)
assert stats.filter_logical_depth == 1
assert stats.filter_logical_fan_out == 2
assert stats.stages[0].filter_logical_depth == 1
assert stats.operator_counts == {"$eq": 2}
```

Depth and fan-out fields are maxima, not totals. See the guide for implicit
conjunction rules, expression boundaries and empty nested pipelines.

::: bondi.mongodb.query_statistics
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true

::: bondi.mongodb.MongoQueryStatistics
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true

::: bondi.mongodb.MongoStageStatistics
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true
