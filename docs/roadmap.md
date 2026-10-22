# Implementation roadmap

Each step is discussed, implemented, verified and reviewed before advancing.
This roadmap is a guide, not a commitment to speculative classes.

| Step | Scope | Acceptance criterion |
| --- | --- | --- |
| 0 | Repository foundation | Editable install, import, pytest, Ruff, documentation build and distribution build work without a database. |
| 1 | MongoCollectionRef | Identify a database and collection without storing a connection. |
| 2 | MongoFindQuery | Construct and inspect a native find query with agreed validation. |
| 3 | Persistence and identity | Save and restore queries with explicit format and fingerprint rules. |
| 4 | MongoAggregateQuery, then CouchbaseQuery | Represent each native query form independently. |
| 5 | Shared query contract | Introduce a minimal protocol justified by concrete types. |
| 6 | WorkloadEntry, then Workload | Preserve order, duplicates, weights and pattern membership in persisted workloads. |
| 7 | First database interaction | Execute a MongoDB query with defined result and resource lifetimes. |
| 8 | Explain support | Collect raw explains and parse MongoDB information without losing the source. |
| 9 | Second backend | Validate shared contracts through Couchbase execution and explains. |
| 10 | Sampling and schemas | Infer document structure from small local samples. |
| 11 | Workload generation | Generate a reproducible workload from one simple pattern. |
| 12 | Research measurements | Run a small repeatable experiment through yanex. |

## Current progress

Steps 0 and 1 are implemented. Step 1 includes collection-reference contract tests,
executable docstring examples and a documentation walkthrough. Step 2 remains
unimplemented pending discussion of the query contract.

## First functional milestone

A student can install the toolkit, construct a MongoDB find query, save it, reload
it and understand every class involved, without running a database.

## Per-component workflow

1. Explain the problem with a concrete usage example.
2. Discuss fields, methods, validation, mutability and exclusions.
3. Implement the smallest useful version.
4. Test meaningful contracts, failure cases and round trips.
5. Walk through the diff and documentation; pause for discussion.

Do not implement later steps in the background. Add tutorial notebooks at coherent
milestones, keeping reusable implementations in the library.
