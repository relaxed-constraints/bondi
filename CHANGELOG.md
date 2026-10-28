# Changelog

## Unreleased

- Check new deployment ports before setup and clean up failed new deployments, with recovery guidance.

- Add the bondi deployment CLI: deploy, start, stop, status, list, logs, and remove.

- Add named local MongoDB deployments through a Python API with packaged Compose assets.
- Support readiness checks, lifecycle management, retained volumes, and explicit data removal.

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
