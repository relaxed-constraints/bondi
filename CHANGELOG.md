# Changelog

## Unreleased

## 0.3.0 — 2026-11-13

### Breaking changes

- Group deployment CLI commands under `bondi deployment`. Use
  `bondi deployment create` instead of `bondi deploy`. Move list, status,
  start, stop, logs and remove into this group. Dataset commands use
  `bondi dataset`. There are no compatibility aliases.
- `Deployment.remove()` now deletes data and saved configuration by default.
  Use `remove(keep_data=True)` to retain them. Remove the `delete_data` argument.
  This aligns Python removal with the CLI (issue #9).
- Move demo loading from `Deployment.load_demo_data()` to
  `bondi.data.load_demo_data(target=..., collection=...)`.
  Replace `bondi load-demo-data` with `bondi dataset load-demo`.
  Use an explicit collection reference and the shared `LoadDataResult`.
  The default mode requires an empty collection. Use upsert for repeat loads.
  Remove `DemoDataResult`. Couchbase now uses the optional SDK for demo loading.
  Create query indexes separately.

### Dataset loading

- Add `load_file`, `load_documents`, `load_hf_dataset` and `load_hf_repository`
  for MongoDB and Couchbase. Support CSV, JSON, JSONL, Parquet, Python dictionaries
  and Hugging Face datasets. File and Hub readers are core dependencies.
- Use `MongoCollectionRef` and the new `CouchbaseCollectionRef` to name exact
  destinations. Hub loads combine all splits by default, or select named splits.
  Repository loading uses dataset names as collection names.
- Support create, upsert and replace modes. Replacement explicitly permits
  clearing the selected collection. No ownership metadata or indexes are created.
- Preserve supplied IDs or use a selected ID field. Generate missing IDs from
  a stable namespace as `gen:` plus 24 hexadecimal characters.
- Add Extended JSON decoding and explicit Couchbase type conversion.
  Support bucket, scope and collection creation, progress callbacks and partial
  failure reports. Result destinations use dotted names.
- Accept managed deployments or explicit connections. MongoDB connections support
  optional username and password fields. CLI connection files support password_env.
- Add dataset guides, an API reference, a notebook and live type-conversion tests.

### CLI and documentation

- Use Click and Rich for CLI parsing and readable tables. Add `--json` to
  `bondi dataset list`. Show unhealthy deployments in red and removed ones in
  dim grey, with `(data retained)` when their volume exists.
- Reorganize the guides from simple examples to advanced options. Update notebooks
  and the AI agent skill for the new APIs and commands.
- Add dataset loading to the homepage and place deployment and loading first in
  the User guide. Show the root changelog under Development without duplicating it.

## 0.2.0 — 2026-11-13

- Add `ByPattern` load selection with weighted, uniform or sequential pattern
  selection and independent uniform or sequential instance streams.
  Include validation, documentation and a MongoDB notebook example that compares
  expected and observed pattern shares with 3:1 weights.

- Add linked uv and pip tabs for installation, notebooks, and contributor workflows.

- Add a MongoDB load-generation notebook with a disposable demo database,
  selection policies, result summaries, streamed callbacks and cleanup.
  Link the notebook from the Tutorials page.

- Simplify the execution and load-generation guides and load API descriptions
  with shorter sentences, plain wording and definitions of phase terms.

- Keep executor API pages focused on generated references; consolidate timing,
  native options, callbacks and health-check explanations in the user guides.

- Link selection policies directly from each executor’s `generate_load()` API
  parameter documentation. Document and link callback function type aliases
  from `on_result`, including the synchronous versus asynchronous distinction.

- Add sync/async executor `generate_load()` with per-client weighted random,
  uniform random and sequential selection, shared warm-up/measurement boundaries,
  cooperative draining, streamed callbacks and optional observation retention.
  Add `LoadResult` with terminal stop reasons and derived duration; inherit executor
  health/error policies and preserve unresolved drain-expiry observations.

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
