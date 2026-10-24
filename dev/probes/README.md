# Couchbase edition evaluation

`couchbase-editions.json` records read-only probes captured on 2026-10-24 using
Couchbase Community and Enterprise 7.6.2 (native ARM64 Docker images) and Python
SDK 4.6.3. Both databases contain the eight synthetic `dev/business.json` documents.
These tiny runs demonstrate response structure, not comparative performance.

Reproduce after starting and initializing both environments:

```sh
uv run --with couchbase==4.6.3 --no-project python \
  scripts/probe_couchbase_profile.py /tmp/couchbase-editions.json
```

No SDK dependency is added to the toolkit: uv supplies it in an isolated environment.
The script only issues read-only SELECT and EXPLAIN statements, consumes all rows,
reads metadata and closes both clients. It asserts result equivalence and the
presence/absence of profiles for these specific editions and versions.

Observed:

- `EXPLAIN`: a plan in the result row, without execution profiling. Its metrics
  concern generating that plan, not executing the underlying SELECT.
- Ordinary SELECT: execution metrics and rows, no profile.
- Enterprise `phases`: CPU time, phase counts, operator counts and phase times.
- Enterprise `timings`: those fields plus `executionTimings`, containing the
  executed operator tree and each operator's `#stats`.
- Community `timings`: rows and basic metrics, but no profile or warning.
- The filtered Enterprise query has an IndexScan3 on `city_stars` emitting 3 items,
  a Fetch processing 3 documents, and a Filter emitting 1 result.
- The covering query emits 3 rows and has no Fetch operator.
- Grouping reads 8 documents and emits 3 city groups.

Keep native operator counters distinct from MongoDB's documents/keys examined.
In particular, index output counts do not establish internal index entries examined.
Metrics are normalized from SDK duration/counter wrappers into milliseconds/integers;
rows and profile objects retain their native JSON structures. No toolkit executor
or profile parser has been implemented as part of this evaluation.
