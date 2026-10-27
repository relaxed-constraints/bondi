# Releases and publishing

## Current release

[0.1.0 is published on PyPI](https://pypi.org/project/bondi/0.1.0/) with a matching
[GitHub release](https://github.com/relaxed-constraints/bondi/releases/tag/v0.1.0).
The tagged source provides the notebooks and Docker environment. Installation
instructions on this site include post-release documentation corrections.

## Maintainer procedure

1. Run offline CI and local database integration tests. Review the changelog and version.
2. For the first publication, configure the PyPI trusted publisher for project `bondi`, owner
   `relaxed-constraints`, repository `bondi`, workflow `release.yml`, environment `pypi`.
3. Create a `v0.1.0` tag at the reviewed commit and publish its GitHub release.
4. The release workflow reruns CI, checks tag/version agreement, and publishes the
   tested wheel and source distribution using OIDC. No API token is stored.
5. Verify a fresh `pip install bondi==0.1.0` and the optional Couchbase extra.
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

After initializing local MongoDB and Couchbase, maintainers can run:

```sh
BONDI_GENERATION_LIVE=1 BONDI_ESTIMATOR_LIVE=1 BONDI_SYNC_LIVE=1 \
  uv run --extra couchbase pytest -q
```

Additional Community/Enterprise executor probes use the opt-in variables documented
in `tests/test_couchbase_executor_live.py`. Never point these tests at private research
data. Notebooks and Docker assets ship in the tagged GitHub source archive; the
PyPI wheel contains the library and license.
