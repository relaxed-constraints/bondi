# Releases and publishing

## Current release

Version 0.2.0 adds sustained query load generation for MongoDB and Couchbase.
Executors support warm-up, measurement, draining and streamed result callbacks.
Selection policies choose individual queries or patterns with explicit weights.
The release also adds a MongoDB tutorial and updates the documentation theme.

See the [load generation guide](load-generation.md), [tutorials](tutorials.md), and
[changelog](https://github.com/relaxed-constraints/bondi/blob/main/CHANGELOG.md).
Release artifacts: [PyPI](https://pypi.org/project/bondi/0.2.0/) and
[GitHub v0.2.0](https://github.com/relaxed-constraints/bondi/releases/tag/v0.2.0).

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
3. Create a `v0.2.0` tag at the reviewed commit and publish its GitHub release.
4. The release workflow reruns CI, checks tag/version agreement, and publishes the
   tested wheel and source distribution using OIDC. No API token is stored.
5. Verify a fresh `pip install bondi==0.2.0` and the optional Couchbase extra.
6. Update installation instructions and the release status/changelog after verification.

Use a new version for each release; do not replace a published tag or distribution.
The library is an early research release: record its version with experiment artifacts.

## Documentation

GitHub Pages builds on published releases, so student documentation follows released
code. The Documentation workflow also supports manual dispatch for the initial
pre-release site or an explicitly reviewed documentation correction. Pull requests
build the documentation without deploying it.

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
Lifecycle and demo-loader tests create separate deployments because they exercise
stop/remove/restart and mutate their own fixtures.

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
