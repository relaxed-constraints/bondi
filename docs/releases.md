# Releases and publishing

## Current release

Version 0.1.8 adds explicit MongoDB and Couchbase deployment versions through
Python `version=` and CLI `--version`. Existing deployments retain saved images,
and conflicting explicit requests fail before Docker access. See the
[deployment guide](deployment.md#database-versions) and
[changelog](https://github.com/relaxed-constraints/bondi/blob/main/CHANGELOG.md).

The tagged source provides self-contained notebooks and the agent skill; the
installed package includes deployment Compose assets and the demo dataset.

## 0.1.8 verification

Local release checks passed on 2026-11-07: 929 offline tests passed with one
database-dependent test skipped, and all seven disposable MongoDB/Couchbase
deployment and demo-data integration tests passed. Ruff lint/format, the strict
documentation build and wheel/source-distribution validation passed.

A fresh wheel installation with the Couchbase extra verified explicit MongoDB
8.0.16 and Couchbase Enterprise 7.6.12 deployments against their server versions,
rejection of conflicting version requests without file changes, and omitted-version
reuse after stop. All release-test deployments were removed.

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
3. Create a `v0.1.8` tag at the reviewed commit and publish its GitHub release.
4. The release workflow reruns CI, checks tag/version agreement, and publishes the
   tested wheel and source distribution using OIDC. No API token is stored.
5. Verify a fresh `pip install bondi==0.1.8` and the optional Couchbase extra.
6. Update installation instructions and the release status/changelog after verification.

Use a new version for each release; do not replace a published tag or distribution.
The library is an early research release: record its version with experiment artifacts.

## Documentation

GitHub Pages builds on published releases, so student documentation follows released
code. The Documentation workflow also supports manual dispatch for the initial
pre-release site or an explicitly reviewed documentation correction. Pull requests
build the documentation without deploying it.

## CI and local integration tests

CI runs offline tests on Python 3.11–3.14, Ruff, a strict MkDocs build, distribution
checks and wheel installation in a fresh environment. No database containers run
in CI. Database-backed tests are explicitly excluded there.

Managed-deployment tests create and remove their own isolated databases. Start Docker, then run:

```sh
BONDI_DEPLOYMENT_LIVE=1 \
  uv run --extra couchbase pytest tests/test_deployment_live.py tests/test_couchbase_deployment_live.py tests/test_demo_data_live.py -q
```

Other live suites require their documented disposable database fixtures first:

```sh
BONDI_GENERATION_LIVE=1 BONDI_ESTIMATOR_LIVE=1 BONDI_SYNC_LIVE=1 \
  uv run --extra couchbase pytest -q
```

Additional Community/Enterprise executor probes use the opt-in variables documented
in `tests/test_couchbase_executor_live.py`. Never point these tests at private research
data. Notebooks and Docker assets ship in the tagged GitHub source archive; the
PyPI wheel contains the library, deployment assets, demo data and license.
