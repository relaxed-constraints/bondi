---
render_macros: true
---

# Releases and publishing

## Current release

Version {{ bondi_version }} standardizes database access on `MongoConnection` and
`CouchbaseConnection` settings. Managed databases expose `deployment.connection`;
executors use `from_connection()`, loaders accept `connection=`, and collection
arguments and attributes use `collection` throughout the Python API.

Synchronous executors also expose lazy native `client` (MongoDB) and `cluster`
(Couchbase) handles. Each has a separate connection pool that closes with its executor.
Deployment `start()` and `stop()` return the handle; `remove()` returns `None`.

This is a breaking SDK release. Saved query and pattern formats remain unchanged.
See the [connection guide](connections.md), [executor guide](executor.md) and
[changelog](changelog.md) for the public API and breaking changes.
Release artifacts are available on [PyPI](https://pypi.org/project/bondi/{{ bondi_version }}/)
and [GitHub](https://github.com/relaxed-constraints/bondi/releases/tag/v{{ bondi_version }}).

## 0.4.0 verification

On 2026-11-20, all 1,634 offline tests passed. The 201 live cases passed across
MongoDB, Couchbase Community and Couchbase Enterprise: the full run passed 200
cases, and a focused rerun passed after correcting a stale AptMQL test helper import.
The rerun also exercised direct synchronous SDK handles on all three backends.
Coverage included deployment restarts, loading and BSON conversion, execution,
health checks, index lifecycle, sustained load, estimation and query conversion.
Test-owned deployments were removed; existing deployments were retained.

Ruff lint and whole-repository formatting, shared documentation configuration,
the strict documentation build, wheel/source builds and Twine checks passed.
A fresh wheel installation with the Couchbase extra passed dependency and CLI
checks, connection/factory checks, query/index/schema persistence and synchronous
MongoDB native-handle lifecycle checks.

## 0.3.8 verification

On 2026-11-17, all 1,591 offline tests and four focused live index tests passed.
The live checks covered explicit backend creation and generic dispatch with managed
MongoDB/Couchbase deployments, replacement, named removal, repeated cleanup and
primary-index preservation. Disposable test deployments were removed. Unrelated
live deployment, loader and executor suites were not rerun for this index-only change.

Ruff, documentation configuration, strict documentation, distribution builds and
Twine checks passed. A fresh wheel installation with the Couchbase extra passed
dependency, public API, dispatch and IndexSet serialization checks. Old backend
function names are absent; this release intentionally breaks those imports.

## 0.3.7 verification

On 2026-11-16, all 1,527 offline tests and both focused live index suites passed.
The live checks created whitespace-containing field indexes on MongoDB and
Couchbase, including nested paths. Disposable test deployments were removed.
The full 199-test live suite had passed for 0.3.6 earlier the same day; this patch
reran the affected index suites rather than all deployment and loader tests.

Ruff, documentation configuration, strict documentation, distribution builds and
Twine checks passed. A fresh wheel installation with the Couchbase extra passed
dependency and serialization checks, including shared whitespace-containing paths.

## 0.3.6 verification

On 2026-11-16, all 1,517 offline tests and all 199 Docker integration tests passed.
The live suite covered MongoDB and both Couchbase editions, including index
creation, readiness and native options. Test-owned deployments were removed.

Ruff, documentation configuration checks, the strict documentation build, wheel/source
builds and Twine validation passed. A fresh wheel installation with the Couchbase
extra passed dependency, CLI, query and index serialization checks. Current-version
labels, links and commands were verified in rendered HTML and exported Markdown.

## 0.3.5 verification

On 2026-11-16, all 1,479 offline tests and all 197 Docker integration tests passed,
covering MongoDB and both Couchbase editions. Fixture-owned deployments and their
data were removed after testing. AptMQL checks loaded the pinned beer_factory
source into MongoDB and Couchbase, verified counts, compared all MongoDB documents,
and checked Couchbase keys and sampled converted values.

Ruff lint and formatting, documentation configuration checks, the strict documentation
build, wheel/source builds and Twine validation passed. A fresh wheel installation
with the Couchbase extra passed dependency, import, CLI, query-serialization and
pinned AptMQL discovery checks. The bundled skill documents the 0.3.5 loaders.

## 0.3.4 verification

On 2026-11-15, all 1,462 offline tests and all 195 Docker integration tests
passed, covering MongoDB and both Couchbase editions. The isolated test
deployments were cleaned up after the run.

Ruff, documentation configuration checks, the strict documentation build,
wheel/source builds and Twine validation passed. A fresh wheel installation
with the Couchbase extra passed dependency, API, CLI and query-serialization
checks. A real Hub JSONL source was read repeatedly through the cached reader.

The bundled skill was updated for deployment globs, creation timestamps and
Hugging Face cache defaults. Local installer discovery and installation into a
disposable project passed; behavior in other coding agents was not tested.

## 0.3.3 verification

All 1,396 offline tests passed locally on 2026-11-15. Ruff, the strict
documentation build, distribution checks and a fresh wheel installation with
the Couchbase extra passed. Installed-package checks covered dependencies,
CLI help, deployment API arguments and query serialization.

All 195 live tests passed across sequential groups, including MongoDB and both
Couchbase editions. The initial combined run exhausted Docker's local network
address pools; splitting the tests avoided changing other deployments. The
shared loader fixture explicitly reserves Data capacity for additional buckets.

## 0.3.2 verification

All 1,564 tests passed locally on 2026-11-15, including 195 Docker-backed tests.
The Windows compatibility fixes passed the hosted Windows offline suite and
PowerShell CLI checks. Live Windows deployments remain unverified.

Ruff, the strict documentation build, distribution checks, and fresh wheel
installation with the Couchbase extra passed.

## 0.3.1 verification

On 2026-11-14, all 1,364 offline tests and all 195 live tests passed.
The live suite covered MongoDB and both Couchbase editions, including fresh
deployment restarts and replacement loads into new collections.

Ruff, the strict documentation build, distribution checks and a fresh wheel
installation with the Couchbase extra passed. The installed package passed
dependency, CLI, import and query round-trip checks.

## 0.3.0 verification

Ruff lint and formatting, the strict documentation build, wheel and source builds,
and Twine validation passed. A fresh wheel installation passed API, CLI, dependency
and packaged-data checks.

The dataset notebook passed its file and Python-document examples, plus Adult
training and combined-split loads. The optional whole-repository download was not run.
All 1,537 tests passed on 2026-11-13, including the full live MongoDB and
Couchbase suite. Test deployments were removed after the run.

## 0.2.0 verification

Local checks passed on 2026-11-13: all 1,456 tests passed, including live MongoDB
and Couchbase tests. The fixtures removed their isolated deployments after testing.
Ruff, the strict documentation build and package builds passed.
The MongoDB notebook also ran successfully, including its 3:1 pattern selection example.

## 0.1.10 verification

Local release checks passed on 2026-11-10: 1,218 offline tests and all 181
isolated Docker integration tests passed, including memory limits and health
checks. Ruff lint/format, strict documentation, distribution validation and
fresh-wheel API checks passed. Research deployments were not modified.

## 0.1.9 verification

Local release checks passed on 2026-11-09: 1,116 offline tests and all 178
Docker-backed integration tests passed. The live suite provisioned isolated BONDI
MongoDB and Couchbase deployments, prepared its own fixtures and removed all test
resources afterward. Existing containers were unchanged.

Ruff lint/format, the strict documentation build and wheel/source-distribution
validation passed. A fresh wheel installation with the Couchbase extra verified
schema snapshot round-trips and further updates, workload persistence, caller-thread
callback delivery, callback signatures for both backends, and bundled assets.

Release CI passed on Python 3.11–3.14; PyPI publication and documentation deployment
completed successfully. A fresh installation of `bondi[couchbase]==0.1.9` from PyPI
passed the same installed-package checks. The published installation, schema and
execution guides, both executor API references and release page were verified.

## 0.1.8 verification

Local release checks passed on 2026-11-07: 929 offline tests passed with one
database-dependent test skipped, and all seven disposable MongoDB/Couchbase
deployment and demo-data integration tests passed. Ruff lint/format, the strict
documentation build and wheel/source-distribution validation passed.

A fresh wheel installation with the Couchbase extra verified explicit MongoDB
8.0.16 and Couchbase Enterprise 7.6.12 deployments against their server versions,
rejection of conflicting version requests without file changes, and omitted-version
reuse after stop. All release-test deployments were removed.

Release CI passed on Python 3.11–3.14; PyPI publication and documentation deployment
completed successfully. A fresh installation of `bondi[couchbase]==0.1.8` from PyPI
verified Python/CLI version options, MongoDB query persistence/statistics, Couchbase
imports and bundled assets. The published deployment guide, API reference and
release page were checked.

## 0.1.7 verification

Published on 2026-11-07. Local release checks passed: 1,038 tests passed and six
were skipped, including enabled disposable MongoDB/Couchbase deployment tests,
MongoDB generation/estimation tests and 163 conversion comparisons. The separately
selected MongoDB notebook-style integration test also passed. Ruff lint/format,
the strict documentation build, wheel/source-distribution validation and a fresh
wheel installation passed.

Release CI passed on Python 3.11–3.14; PyPI publication and documentation deployment
completed successfully. A fresh installation of `bondi[couchbase]==0.1.7` from PyPI
verified conversion, statistics (including structural depth), BSON persistence,
Couchbase imports and bundled demo data. The published statistics guide and API
reference were checked for the new metrics.

## Maintainer procedure

1. Run offline CI and local database integration tests. Review the changelog and version.
   Review the [agent skill](agent-skill.md) against the release API, including examples,
   documentation links and installation from the source containing the skill.
2. For the first publication, configure the PyPI trusted publisher for project `bondi`, owner
   `relaxed-constraints`, repository `bondi`, workflow `release.yml`, environment `pypi`.
3. Create a `v{{ bondi_version }}` tag at the reviewed commit and publish its GitHub release.
4. The release workflow reruns CI, checks tag/version agreement, and publishes the
   tested wheel and source distribution using OIDC. No API token is stored.
5. Verify a fresh `pip install bondi=={{ bondi_version }}` and the optional Couchbase extra.
6. Update installation instructions and the release status/changelog after verification.

Use a new version for each release; do not replace a published tag or distribution.
The library is an early research release: record its version with experiment artifacts.

## Documentation

GitHub Pages builds on published releases, so student documentation follows released
code. Pull requests build the documentation without deploying it.

## CI and local integration tests

CI runs offline tests on Python 3.11–3.14, Ruff, a strict Zensical build, distribution
checks and wheel installation in a fresh environment. CI selects `-m "not live"`;
no database containers run there.

All database-backed suites share one opt-in. Start Docker, then run the tests.
For pip, use the development environment from [Contributing](contributing.md#setup).

=== "uv"

    ```sh
    BONDI_LIVE=1 uv run --extra couchbase pytest -m live -v
    ```

=== "pip"

    ```sh
    python -m pip install -e ".[couchbase]"
    BONDI_LIVE=1 python -m pytest -m live -v
    ```

To select a smaller suite, pass its file instead:

=== "uv"

    ```sh
    BONDI_LIVE=1 uv run pytest tests/test_executor_mongodb.py -q
    BONDI_LIVE=1 uv run pytest tests/test_mongodb_conversion_live.py -q
    BONDI_LIVE=1 uv run --extra couchbase pytest tests/test_couchbase_executor_live.py -q
    ```

=== "pip"

    ```sh
    BONDI_LIVE=1 python -m pytest tests/test_executor_mongodb.py -q
    BONDI_LIVE=1 python -m pytest tests/test_mongodb_conversion_live.py -q
    BONDI_LIVE=1 python -m pytest tests/test_couchbase_executor_live.py -q
    ```

Without `BONDI_LIVE=1`, all tests marked `live` are skipped before fixture setup.
The older per-suite flags and externally supplied test-server URIs are no longer
used. No manual database initialization or credentials are needed.

### Deployment ownership

The shared fixtures in `tests/conftest.py` lazily create BONDI-managed MongoDB,
Couchbase Community and Couchbase Enterprise deployments in a temporary registry.
They load the packaged demo collection and the Couchbase `city_stars` index needed
by executor probes. Each backend/edition is reused within the test session and
removed, including its data, during teardown—even when a test or demo setup fails.
Lifecycle tests create separate deployments for stop/remove/restart checks.
Demo-loader tests use separate collections in the shared fixtures.

Tests never look up or reuse your normal BONDI deployments. The temporary registry
produces distinct Docker project identities; cleanup only targets deployments
created by the tests. Startup failures use BONDI's existing rollback behavior.
A hard process kill or unavailable Docker daemon can prevent teardown; in that
case inspect the temporary test registry and remove only its test deployments.

### Dedicated test ports

The harness probes these ten-slot pools and skips occupied ports/groups:

| Backend | Test pool |
| --- | --- |
| MongoDB | `27117–27126` |
| Couchbase management | `8191 + 10 × slot` |
| Couchbase query | `8193 + 10 × slot` |
| Couchbase KV | `11310 + 10 × slot` |

Couchbase `slot` runs from 0 through 9; the first two groups are
`8191 / 8193 / 11310` and `8201 / 8203 / 11320`. These start 100 above the
standard ports, leaving the first ten ordinary MongoDB ports and ten Couchbase
groups spaced by ten available for regular deployments. The separate MongoDB
range `20217–20227` is also untouched.

Every test deployment claims a distinct slot for the duration of the test process,
including while stopped or removed during lifecycle testing. If no slot is free,
setup fails clearly instead of falling back to standard ports. Port probes are
advisory: another process can race Docker's bind, which fails rather than taking
over that process. Run the live suite serially; parallel pytest workers and
concurrent live runs are not supported by this per-process allocator.

The full suite starts both Couchbase editions and may pull their pinned Docker
images. Docker needs capacity for the fixtures in addition to existing containers.
Notebooks and Docker assets ship in the tagged GitHub source archive; the PyPI
wheel contains the library, deployment assets, demo data and license.
