# Changelog

## Unreleased

- Add linked uv and pip tabs for installation, notebooks, and contributor workflows.

- Migrate the documentation to Zensical’s modern theme and native
  `zensical.toml` configuration. Follow the reader’s system colour preference
  by default, offer a light and dark mode toggle, and highlight search matches
  on result pages.

- Show formatted API signatures in separate code blocks, with linked return
  annotations and descriptions of what each value-returning callable returns.

## 0.1.10 — 2026-11-10

- Add bounded sync/async executor ping and optional health_check_timeout_seconds
  for MongoDB and Couchbase Query service. Enabled checks stop workload scheduling
  on availability/access failures while draining callbacks; defaults are unchanged.
  Add DatabaseUnavailableError and separate health_check_elapsed_ms result timing.

- Add optional MongoDB container memory and WiredTiger cache limits through Python
  and CLI, persisted on deployment handles and shown in status output. Differing
  requests for existing MongoDB deployments warn and retain existing settings;
  legacy metadata and manually maintained Compose assets remain unchanged.

## 0.1.9 — 2026-11-09

- Make live integration tests self-contained with shared, isolated BONDI deployment
  fixtures and one `BONDI_LIVE=1` opt-in. Allocate dedicated high-numbered test ports,
  prepare demo data/indexes automatically, and clean up only test-owned deployments.

- Add optional `on_result(position, entry, result)` to run/explain/profile workload
  methods on MongoDB and Couchbase executors. Serialize callbacks per workload,
  support awaitable callbacks in async executors, and execute synchronous callbacks
  on the caller thread. Preserve input-aligned results and fail-fast draining;
  propagate callback failures after cancellation and cleanup.

- Add atomic `Schema.save()` and validated `Schema.load()` for versioned JSON
  snapshots, preserving observations, retained scalar values and further updates.
  Reuse Canonical Extended JSON with Python scalar adapters; document fixed-offset
  datetime restoration and the exclusion of global field order. Show direct
  `Schema.save` and `Workload.save` callbacks in Yanex artifact examples.

## 0.1.8 — 2026-11-07

- Add optional `version=` / `--version` selection for MongoDB and Couchbase
  deployments, preserving pinned defaults and saved images on reuse. Reject
  explicit version conflicts before Docker access, support legacy image metadata,
  and include the image in Docker failure diagnostics.

## 0.1.7 — 2026-11-07

- Extend MongoDB query statistics with expression depth, filter logical depth and
  fan-out, and recursive pipeline depth (including empty child pipelines).
  Document precise structural rules without changing existing version-1 counts.

- Add `query_statistics()`, `MongoQueryStatistics` and `MongoStageStatistics` for
  versioned MongoDB predicate, operator and stage counts, including optional nested
  pipelines and find normalization. Document complete rules in the new
  MongoDB Query statistics user guide.

- Add `MongoFindQuery.to_aggregate()` for independent, ordered conversion of supported
  find queries, with explicit errors for unsupported constructs.
- Translate top-level `$slice`, bounded `$elemMatch`, and explicitly bound positional
  `$` projections, with opt-in live find/aggregation equivalence tests.

## 0.1.6 — 2026-11-05

- Add Couchbase `memory_limit_mb` / `--memory-limit-mb` for configurable container
  limits, retaining the 4096 MiB default, persisted settings and conflict checks.
  Document data-preserving resizing for existing deployments.

## 0.1.5 — 2026-11-03

- Expose `bondi.mongodb.loads_query_json` for strict external JSON input with
  query-aware BSON decoding, preserved regex operators and normalized decode errors.

- Preserve MongoDB `$regex`/`$options` operator documents during query and workload
  round trips, including `$elemMatch`; native BSON regex values use `$regularExpression`.
- Add BSON-aware find projections in version-2 query envelopes. Version-1 reads retain
  plain-JSON projection semantics; new find fingerprints change with the new format.
  Ambiguous literal BSON-wrapper documents remain rejected on save.

- Add a Projects documentation page linking to the demo and minimal starter projects.

- Add a portable BONDI agent skill with API/CLI guidance, development conventions,
  a documentation and tutorial map, and an installation guide.
- Add `MongoCollectionRef.from_namespace(namespace)` to create a collection reference
  by splitting at the first dot, preserving additional dots in the collection name.
  Validate input types, the separator, empty names and null characters.

## 0.1.4 — 2026-10-31

- Add Community/Enterprise Couchbase deployment, cluster/bucket initialization, custom ports and CLI support.

- CLI removal now deletes data by default with confirmation; use --keep-data to retain it or -y to skip confirmation.

- Check new deployment ports before setup and clean up failed new deployments, with recovery guidance.

- Add the bondi deployment CLI: deploy, start, stop, status, list, logs, and remove.

- Add named local MongoDB deployments through a Python API with packaged Compose assets.
- Support readiness checks, lifecycle management, retained volumes, and explicit data removal.

- Add packaged demo-data loading through `Deployment.load_demo_data()` and `bondi load-demo-data`.
- Make database notebooks self-contained with deployment setup and complete data cleanup.
- Expand Quickstart to six workflows and consolidate tutorials with VS Code instructions.
- Improve API reference headings, syntax highlighting, navigation and local documentation guidance.

## 0.1.3 — 2026-10-28

- Add versioned MongoQueryPattern serialization with to_dict/from_dict and to_json/from_json.
- Preserve BSON operands and query options when saving and restoring patterns.
- Document pattern persistence with examples and round-trip tests.

## 0.1.2 — 2026-10-28

- Add human-readable MongoQueryPattern string representations.
- Return independent, JSON-serializable dictionaries for generation statistics.
- Update generation documentation and notebook examples.

## 0.1.1 — 2026-10-27

- Rewrite the README around implemented features, with synchronous usage examples.
- Clarify installation, notebook setup and published documentation links.
- No library behavior or public API changes.

## 0.1.0 — 2026-10-27

- Native MongoDB find/aggregation and Couchbase SQL++ queries with JSONL workloads.
- Synchronous and asynchronous execution, explain and profile operations.
- Offline query summaries, schema inspection and optional value retention.
- MongoDB sampling estimation and pattern-based workload generation.
- Student notebooks, local Docker environments and documentation.

This is an early research release. Public APIs and persistence formats may change
in subsequent releases; retain the package version alongside experiment artifacts.
