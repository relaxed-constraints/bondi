# Releases and publishing

## Current release

[0.1.4 is published on PyPI](https://pypi.org/project/bondi/0.1.4/) with a matching
[GitHub release](https://github.com/relaxed-constraints/bondi/releases/tag/v0.1.4).
The tagged source provides the self-contained notebooks. The installed package
includes deployment Compose assets and the demo dataset.

## Maintainer procedure

1. Run offline CI and local database integration tests. Review the changelog and version.
2. For the first publication, configure the PyPI trusted publisher for project `bondi`, owner
   `relaxed-constraints`, repository `bondi`, workflow `release.yml`, environment `pypi`.
3. Create a `v0.1.4` tag at the reviewed commit and publish its GitHub release.
4. The release workflow reruns CI, checks tag/version agreement, and publishes the
   tested wheel and source distribution using OIDC. No API token is stored.
5. Verify a fresh `pip install bondi==0.1.4` and the optional Couchbase extra.
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
