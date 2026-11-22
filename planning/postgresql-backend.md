# PostgreSQL backend spike

**Status (2026-11-22).** Design proposal. The API names and storage layout below are candidates for review. The first live experiment is recorded under Findings and decisions.

The question for this spike is whether a researcher can load the same document dataset used with MongoDB and Couchbase, express a workload in native PostgreSQL, create the intended indexes, and interpret the results using BONDI's existing contracts. The first milestone is one repeatable end-to-end example.

## Deployment and connection

Propose `deploy_postgresql(...)`, a matching CLI backend, and a packaged Compose template using the official `postgres` image. Pin an image version for the spike, record it with the findings, and choose the volume mount for that major version. PostgreSQL 18 introduced a change to the official image's data directory layout. Expose a configurable localhost port and return immutable `PostgresConnection` settings from `deployment.connection`. The same settings should support a separately managed server.

Review the MongoDB-or-Couchbase branches in deployment descriptor loading, image selection, credentials, and port mappings. Preserve existing saved deployments. Verify authenticated readiness, status and logs. Insert a sentinel document, stop and restart the deployment, and read it back. On disposable instances, exercise both removal modes, including reattaching retained data. [Deployment implementation](../src/bondi/deployment/_deployment.py) · [Official image](https://hub.docker.com/_/postgres)

## Collections, document identity, and data loading

Connect to one PostgreSQL database. Within it, map a dataset to a schema, a collection to a table, and a document to one row. Try a `PostgresCollectionRef(schema, table)` and the following managed layout.

```sql
CREATE TABLE yelp.business (
    document_id text PRIMARY KEY,
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object')
);
```

Use JSONB for indexing and document queries. It normalizes object key order and duplicate keys. Native queries can also access existing JSON columns and relational tables. Only operations that require a known document column need the managed layout. [PostgreSQL JSON types](https://www.postgresql.org/docs/current/datatype-json.html)

Before adopting a text primary key, check generated keys, explicit IDs with different source types, values such as 1 and "1", and duplicate IDs in one input. Decide which identifying fields stay in the document. Exercise BSON-specific values through the loader's conversion policy. Verify that create requires an empty destination, replace preserves indexes, and upsert replaces matching documents while retaining others. Record acknowledged writes when a batch fails. A document reader that yields the inner JSON objects can feed the existing offline Schema class. [Loader](../src/bondi/data/_loader.py) · [Schema](../src/bondi/schema.py)

## Native query representation

Prefer `PostgresQuery` over a generic `SQLQuery`. The existing Query protocol already shares validation, serialization, and fingerprinting across backends. SQL dialect, operators, and parameter binding belong to the native representation. Try the backend identifier `postgresql` and versioned query kind `postgresql.sql`. Preserve statement text exactly, including invalid SQL that a consumer wants to evaluate. Keep each workload single-backend and exercise JSONL save/load and fingerprint round trips. [Query protocol](../src/bondi/query.py) · [Workload](../src/bondi/workload.py)

```python
# Proposed API
query = PostgresQuery(
    "SELECT doc FROM yelp.business WHERE doc ->> 'city' = %s",
    positional_parameters=["Melbourne"],
)
```

Start with positional scalar parameters. Before accepting structured parameters, decide how a saved workload distinguishes a PostgreSQL array from a JSON array and how JSON objects are bound on replay.

## Executor and results

**Psycopg 3** is a PostgreSQL driver for Python. The Python package is called `psycopg`. It opens connections to the PostgreSQL server, binds Python values to SQL parameters, and reads the returned rows. Docker provides the server. Psycopg would be an optional dependency for clients running PostgreSQL operations. Query objects and offline plan parsing should work without it. [Psycopg documentation](https://www.psycopg.org/psycopg3/docs/)

Try an AsyncPostgresExecutor backed by a bounded connection pool and a PostgresExecutor using BONDI's synchronous facade. Work on one connection is serialized and shares transaction state, so use separate connections for concurrent operations. Specify ownership for supplied and executor-created pools. Include pool acquisition and result consumption in deadlines. After cancellation or a statement error, verify that the next borrower receives a usable connection. [Psycopg concurrency](https://www.psycopg.org/psycopg3/docs/advanced/async.html) · [BONDI architecture](../docs/architecture.md)

| Operation | PostgreSQL mechanism | Expected ExecutionResult |
| --- | --- | --- |
| run | Execute once and consume all rows | Client elapsed time and output count. Retain rows only when requested. Check memory usage on large results. |
| explain | EXPLAIN (FORMAT JSON) | Estimated plan in raw. Leave output count and documents unset. |
| profile | EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) | Execute once and retain the instrumented plan. PostgreSQL discards query output rows. Leave output count and documents unset. |

Start with read workloads and use read-only transactions, since EXPLAIN ANALYZE executes the supplied statement. For collected output, try named rows. Selecting doc would produce a row with a single doc key. Test aliases, duplicate column labels, and scalar aggregates before settling the row contract. [PostgreSQL EXPLAIN](https://www.postgresql.org/docs/current/sql-explain.html)

Keep the native JSON explain array under an `explain` key in ExecutionResult.raw, which accepts a dictionary. An offline summary parser can report plan node types in traversal order, index names for supported plans, server execution time, and root actual rows for supported single-loop reads. Client elapsed time and instrumented server execution time measure different intervals. Retain loop counts, buffer activity, heap fetches, and filter removals in the native plan. Leave documents_examined and keys_examined unknown unless a supported source supplies the defined whole-operation metric. [ExecutionResult](../src/bondi/execution.py) · [QuerySummary](../src/bondi/summary.py)

## Index definitions and lifecycle

Reuse the Couchbase pattern of a native PostgresIndex independent of FieldIndex. Exercise versioned IndexSet persistence, create one or many, and remove by name. Quote schema, table, and index identifiers separately when composing DDL. A native definition should preserve the method, indexed expression, and operator class needed to reproduce the experiment. [BONDI index definitions](../src/bondi/indexes.py) · [Couchbase index lifecycle](../src/bondi/couchbase/indexes.py)

| Workload predicate | Candidate index definition |
| --- | --- |
| Text equality on city | B-tree expression index on (doc ->> 'city') |
| Numeric range on stars | B-tree expression index on ((doc ->> 'stars')::numeric) |
| JSONB containment with @> | GIN on doc. Compare the default jsonb_ops with jsonb_path_ops for the chosen operators. |

Match the predicate and index expression in each experiment. Numeric casts can fail on mixed-type documents. Text extraction changes numeric ordering. Defer FieldIndex translation until its type and comparison semantics can be specified. Before supporting batch replacement, test protection of primary keys, unique and exclusion constraints, and index ownership on the intended table. Preserve BONDI's partial-progress reporting for batch operations. [PostgreSQL JSONB indexing](https://www.postgresql.org/docs/current/datatype-json.html#JSON-INDEXING)

## Evaluation sequence

1. **Define the fixture and expected answers.** Pick an existing dataset, include nested objects, arrays, missing fields, JSON nulls, and mixed numeric values. Write native queries for equality, range, containment, and aggregation. Record expected IDs or counts for equivalent queries across backends.
2. **Run one vertical spike.** Deploy a disposable instance, load the fixture, bind a value, and run the four queries. Save estimated and actual plans before and after creating expression and GIN indexes. Record dataset size and planner statistics. A sequential scan can be the expected choice on a small table.
3. **Review public contracts.** Use the observed rows and plans to decide identity encoding, parameter representation, row shape, summary coverage, and native index definitions. Document any divergence from MongoDB or Couchbase semantics.
4. **Integrate in increments.** Review deployment and connection first, then query persistence, executor and summaries, and finally loaders and indexes. Verify sync and async calls, workload order, bounded concurrency, serialized callbacks, health checks, timeout recovery, sustained load, and installation without the driver extra.
5. **Decide first-class scope.** Evaluate deployment, loading, native workloads, diagnostics, and index lifecycle together. Keep PostgreSQL sampling estimation, query generation, and syntax statistics open for future research use cases. [Current roadmap](../docs/roadmap.md)

## Findings and decisions

Append an entry after each experiment. Include the date, PostgreSQL image tag and driver version, dataset or fixture, reproduction command or artifact link, observation, and the decision or remaining question. Move accepted decisions into the relevant section above and retain their evidence here.

### 2026-11-22 · AptMQL beer_factory

The public `load_aptmql_dataset` function loaded a fresh MongoDB 8.0.16 deployment at AptMQL revision `06ba1f0f29b1947e67a343c204e6a9b5eede6b17`. A spike-only Psycopg 3.3.9 COPY writer transferred the documents to the official `postgres:17.5` Docker image. Each collection received a table with a text primary key and a JSONB object column. The probe retained the original string `_id` inside each document and compared every decoded PostgreSQL document, keyed by ID, with its MongoDB source. All 7,724 matched: 24 brands, 554 customers, 118 inventory items, 3 locations, 713 reviews, and 6,312 transactions. This fixture exercises string IDs. Mixed BSON identity types remain open.

The probe ran ANALYZE, bound query parameters through Psycopg, compared complete result sets with independent MongoDB filters or aggregation, and captured estimated and actual JSON plans. It repeated all four queries after adding three secondary indexes and refreshing statistics. The planner chose indexes without hints.

| Query on transactions | Matching output | Before secondary indexes | After secondary indexes |
| --- | ---: | --- | --- |
| Customer ID equals 864896 (string) | 13 IDs | Sequential scan | Bitmap index scan on expression B-tree tx_customer, then heap scan |
| Numeric purchase price below 2 | 220 IDs | Sequential scan | Index scan on numeric expression B-tree tx_price |
| Document contains nested item brand ID 10016 (string) | 537 IDs | Sequential scan | Bitmap index scan on whole-document GIN tx_doc, then heap scan |
| Group by location ID and count | 2 groups | Aggregate over sequential scan | Aggregate over sequential scan |

**Design implications.** The numeric expression index also changed the range cardinality estimate from 2,104 rows to 220, exactly the observed count. The aggregate's child scan produced 6,312 rows and its root produced two, illustrating why the summary parser must read final cardinality at the root. These results support keeping the indexed expression and access method in a native index definition. The next loader decision is how to encode mixed-type IDs and BSON-only values before claiming support across AptMQL datasets.

**Lifecycle observation.** The PostgreSQL container retained all 6,312 transactions after restart. On the first attempt, a readiness check using the original Docker-assigned host port failed. Resolving the port again after restart succeeded on the repeat run. A BONDI-managed deployment should pin its configured host port. Both runs used disposable containers and cleaned them up.

**Reproduction.** Supply `SPIKE_MONGO_URI` and `SPIKE_PG_DSN` for fresh disposable databases, then run the command below from the repository root with Docker services already running. The probe creates the beer_factory MongoDB database and PostgreSQL schema. The caller owns the service lifecycle. The JSON artifact contains all 16 estimated and actual plans across both phases. Elapsed times are single observations.

```sh
uv run --with 'psycopg[binary]==3.3.9' python dev/probes/postgresql_beer_factory.py /tmp/beer-plans.json
```

[Executable probe](../dev/probes/postgresql_beer_factory.py) · [Recorded plans and counts](../dev/probes/postgresql-beer-factory.json)
