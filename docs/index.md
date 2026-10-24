# Database Research Toolkit

`dbrtoolkit` is a small shared foundation for database research projects.
It is being developed incrementally, with each class discussed and understood
before moving on to the next component.

## Current capabilities

The package provides an immutable `MongoCollectionRef` and mutable `MongoFindQuery` and `MongoAggregateQuery` classes.
No database connection is needed; PyMongo is installed automatically for BSON support. Start with the
[collection reference guide](collection-reference.md), then follow the
[documentation walkthrough](documentation.md) to see how its API docs are built.

See the [find-query guide](find-query.md) for construction and mutation examples.

The [aggregation guide](aggregate-query.md) introduces ordered pipelines and
explains how the two native query classes share serialization.

The [Couchbase guide](couchbase-query.md) introduces SQL++ text, parameters and context.

The [workload guide](workloads.md) explains the Query protocol, reference ownership
and single-backend validation.

The [executor guide](executor.md) covers async MongoDB execution, raw explains and
concurrent workloads. The [Couchbase executor guide](couchbase-executor.md) shows
the same operations for SQL++, including optional Enterprise profiling. Database
connections are needed only for execution.

## Where to start

- [Architecture](architecture.md): scope and agreed design boundaries.
- [Roadmap](roadmap.md): small implementation milestones.
- [Contributing](contributing.md): setup, checks and the learning workflow.
- [API reference](api.md): documentation extracted from the package.
