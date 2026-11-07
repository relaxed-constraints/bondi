# MongoDB queries

Find persistence writes version 2 (BSON-aware filter and projection) and reads
versions 1 and 2. Aggregation persistence remains version 1. Both preserve `$regex`
operator documents; native regex values use `$regularExpression`. See the
[codec and compatibility guide](../../find-query.md) for legacy projection and
fingerprint behavior.

`MongoFindQuery.to_aggregate()` converts supported find queries without database
access, including bounded array-projection translations; see [conversion behavior and restrictions](../../find-query.md#convert-a-find-query-to-aggregation).

For structural predicate, operator and stage counts, see the
[query statistics API](statistics.md).

::: bondi.mongodb.MongoCollectionRef
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true

::: bondi.mongodb.MongoFindQuery
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true

::: bondi.mongodb.MongoAggregateQuery
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true

::: bondi.mongodb.loads_query_json
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true
