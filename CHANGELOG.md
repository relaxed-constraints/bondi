# Changelog

## Unreleased

- Standardize database access on `MongoConnection` and `CouchbaseConnection` settings
  exported from `bondi`. Add `Deployment.connection`; replace all executor
  `from_uri()` factories with `from_connection()`. Loaders and index operations
  require connection settings instead of accepting deployments.
  Rename loader `target=` to `connection=` and remove connection exports from
  `bondi.data`. MongoDB executor credentials belong to the connection settings,
  not `client_kwargs`. Validate credential types consistently with `TypeError`
  (breaking change).
- Standardize collection arguments and attributes on `collection`, including
  queries, patterns, workload generators, estimators and single-index operations.
  Rename estimator `sample_target` to `sample_collection` and index error `target`
  to `collection`. Saved query and pattern envelopes and fingerprints retain
  their existing formats (breaking change).
- Return the same deployment handle from `Deployment.start()` and `.stop()`;
  `.remove()` continues to return `None`.

- Upgrade relcon-docs to 0.1.7 and apply shared Markdown defaults, including SmartSymbols arrows.

- Allow manual documentation publishing alongside release-triggered deployment.

- Refresh the documentation homepage introduction to reflect the toolkit's broader
  research and benchmarking capabilities.

- Inherit shared image lightboxes and allow relcon-docs updates within
  `>=0.1.0,<1.0.0`, retaining the lockfile for reproducible documentation builds.

## 0.3.8 — 2026-11-17

- Add top-level index lifecycle dispatchers. Rename backend functions to
  `create_mongo_index[es]`, `remove_mongo_index[es]`, `create_couchbase_index[es]`
  and `remove_couchbase_index[es]`, without compatibility aliases (breaking change).

- Organize native index definitions and lifecycle APIs under the MongoDB and
  Couchbase reference sections, with links from the shared index definitions page.

- Add `replace=True` to batch index creation, clearing secondary
  indexes on included collections while preserving primary indexes. Add name-based
  `remove_index()` and `remove_indexes()` with repeatable cleanup, protected-index
  checks and partial-removal errors. Replacement errors report removals and creations.

## 0.3.7 — 2026-11-16

- Allow whitespace, Unicode and punctuation in shared FieldIndex path segments,
  preserving names exactly and quoting them safely for Couchbase.

## 0.3.6 — 2026-11-16

- Derive current-version documentation labels, links and install commands from
  pyproject.toml instead of maintaining hardcoded release numbers.

- Add shared `FieldIndex`, native `MongoIndex` / `CouchbaseIndex`, and ordered
  `IndexSet` definitions with versioned JSON persistence and config parsing.
- Add synchronous single and batch index creation for deployments or connection
  settings, with build readiness and partial failure reporting. IndexSet keys are
  collection names; batches accept a MongoDB database or Couchbase bucket/scope.
- Export connection settings from `bondi`, preserving `bondi.data` imports.
- Document index definitions and creation, including nested API method navigation.
- Move dataset loading to the first tutorial and clarify the schema inspection title.
- Link the hosted demo and empty project documentation from the Projects page.

## 0.3.5 — 2026-11-16

- Add `load_aptmql_dataset` and `load_aptmql_repository`, with matching
  `bondi dataset load-aptmql` and `load-aptmql-repository` commands. Download
  pinned BSON dumps, preserve dataset namespaces, and use shared MongoDB/Couchbase
  writers with partial receipts. Document the available datasets. Skip dump indexes
  and collection metadata.

## 0.3.4 — 2026-11-15

- Use Hugging Face's disk caches by default for dataset and repository loaders.
  Preserve original JSONL and Extended JSON decoding, including gzip files.
  Add `streaming=True` and CLI `--streaming` to opt into remote streaming.

- Add Image and Created columns to deployment list and bulk lifecycle previews.
  Persist a UTC creation timestamp for new deployments; display — for older ones.

- Support case-sensitive name globs in deployment start, stop and remove commands.
  Show multiple matches with the same full, colored table as deployment list
  and confirm once before acting; add `--yes` / `-y` to
  start and stop as well as remove.

## 0.3.3 — 2026-11-15

- Simplify the database deployment API reference to member documentation; keep
  usage and configuration guidance in the deployment guide.

- Accept explicit Couchbase Data Service, Index Service and bucket memory quotas
  at deployment creation. Default Data and Index to 512 MiB each and the bucket
  to the Data quota. Save and verify resolved quotas at startup, preserving
  existing deployment settings. Reject new budgets with no container headroom.
  Document explicit bucket budgets for multi-bucket setups and reserve capacity
  in live loader fixtures.

- Install relcon-docs 0.1.0 from PyPI and enable shared heading permalinks.

- Update relcon-docs to inherit alphabetical API members and exclude private members.

- Update relcon-docs defaults and deployment workflow; inherit equation rendering,
  diagram accent colours and dark-mode Markdown copy controls.

- Use shared light/dark diagram colours from relcon-docs.

- Inherit callouts, collapsible notes and Mermaid support from relcon-docs.

- Inherit Markdown-export defaults from relcon-docs while retaining BONDI
  documentation and API-reference index sections.

- Use the pinned relcon-docs Pages workflow for deployments triggered only by
  published GitHub releases; remove the manual deployment trigger.

- Adopt relcon-docs as documentation tooling, with managed shared defaults and
  styling, a pinned Git dependency, and configuration-drift checks in CI.

- Split documentation configuration into project-specific YAML and inherited shared
  defaults, preserving the modern theme, API rendering and Markdown exports.

- Batch MongoDB and Couchbase inserts across all dataset loaders, with confirmed
  write counts and uncertainty reporting for partial failures.

## 0.3.2 — 2026-11-15

- Reject ports with active listeners on Windows and make synchronous executor
  interrupt tests portable.

- Default Hugging Face loaders to automatic JSON mode selection using the
  dataset card’s `mongodb-extended-json` tag. Explicit modes override the tag.

- Stream original Hugging Face JSONL splits to preserve missing fields, explicit
  nulls and Extended JSON types.

- Add a manual GitHub Actions workflow for Windows CLI and offline tests.

- Document how to upload and verify Hugging Face dataset repositories for BONDI.

## 0.3.1 — 2026-11-14

- Allow deployment ports to be reused after shutdown when only TCP TIME_WAIT
  connections remain. Continue to reject ports with active listeners.

- Wait for healthy Couchbase nodes and a successful query before creating a missing
  bucket. Use the existing startup deadline. Add repeated Community 8.0.0 restart
  checks for the first-bucket directory conflict.

- Fix Couchbase replacement loads into new collections by skipping the unnecessary
  deletion scan after successful creation. Creation conflicts still fail.
- Preserve the original scan or deletion error if Couchbase scan cancellation also
  fails. Keep driver details redacted in LoadDataError.

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
  `bondi.data.load_demo_data(connection=..., collection=...)`.
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
- Publish a documentation index for AI agents and per-page Markdown exports,
  with a Copy as Markdown button on the HTML pages.

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
