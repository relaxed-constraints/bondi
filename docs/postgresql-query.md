# PostgreSQL queries

A `PostgresQuery` describes one SQL read and its positional parameters. For
BONDI-loaded datasets, the connection URI selects the database, the schema
contains the dataset's tables, and each table stores one document per row in
the `doc` JSONB column. SQL can also read existing relational tables and joins.

## Run your first PostgreSQL query

From a checkout with PostgreSQL support, install the extra, start a deployment,
and load the eight demo businesses into `demo.business`:

```sh
uv sync --extra postgresql
uv run --extra postgresql bondi deployment create postgresql --name pg-demo --database research
uv run --extra postgresql bondi dataset load-demo --deployment pg-demo --schema demo --collection business
```

In the same environment, run this Python example:

```python
from bondi.deployment import get_deployment
from bondi.postgresql import PostgresExecutor, PostgresQuery, summarize

query = PostgresQuery(
    "SELECT doc FROM demo.business WHERE doc ->> 'city' = %s",
    positional_parameters=["Sydney"],
)
with PostgresExecutor.from_connection(get_deployment("pg-demo").connection) as executor:
    result = executor.run(query, collect_results=True)
    businesses = [row["doc"] for row in result.documents]
    plan = summarize(executor.explain(query).raw)
    profile = summarize(executor.profile(query).raw)
```

SQL output labels become dictionary keys. Selecting `doc` yields a row with
one key, while `SELECT count(*) AS n` yields a row with an integer under `n`.
Give collected columns distinct labels. With the default `collect_results=False`,
the executor consumes the stream and reports the row count.

## Bind and save SQL

Psycopg 3 is the Python driver BONDI uses to connect to PostgreSQL, send SQL,
and decode result rows. Use its `%s` placeholder for each positional value. Supply a list of
strings, booleans, integers, finite floats or `None`. For JSONB containment,
bind JSON text and cast it explicitly:

```python
query = PostgresQuery(
    "SELECT doc FROM demo.business WHERE doc @> %s::jsonb",
    ['{"city":"Sydney"}'],
)
```

Construction, fingerprinting and workload persistence operate offline. The
versioned `postgresql.sql` envelope preserves the statement text and bindings.
Execution validates the single-read contract and PostgreSQL resolves names
and types. The same query instance can be passed to `run`, `explain`, or
`profile`. See [execution and type decoding](executor.md#postgresql-reads-and-plans),
[profiling](profiling.md), and [choosing a JSONB index](indexes.md#postgresql-jsonb-indexes).
