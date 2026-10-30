# Couchbase queries

`CouchbaseQuery` holds SQL++ text, parameters and optional query context. It does not
parse SQL++ or translate MongoDB queries. SQL++ can query nested JSON documents
using SQL-style expressions.

```python
from bondi.couchbase import CouchbaseQuery

query = CouchbaseQuery(
    "SELECT RAW b FROM business b WHERE b.city = $city LIMIT 5",
    named_parameters={"city": "Sydney"},
    query_context="demo._default",
)
restored = CouchbaseQuery.from_json(query.to_json())
assert restored.fingerprint() == query.fingerprint()
```

The context selects the bucket and scope. You can instead use the fully qualified
collection name, such as `` `demo`.`_default`.`business` ``, in the statement.
`SELECT RAW b` returns each business directly; `SELECT b` wraps it under a `b` key.
That distinction matters when passing results to the schema parser.

Use parameters for values rather than formatting values into SQL text. Query
objects use JSON-compatible parameter values and remain mutable. The Couchbase SDK
is needed for execution, but not for creating or saving these objects.

Continue with [execution](executor.md) or the [Couchbase tutorial](tutorials.md#explore-couchbase-execution-and-profiling).
See the [query reference](reference/couchbase/queries.md) for positional parameters
and the complete contract.
