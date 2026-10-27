# BONDI — A Python toolkit for document database research

**bondi** provides A Python toolkit for document database research.

Use native MongoDB and Couchbase queries, execute and profile workloads, inspect
schemas, estimate MongoDB selectivity, and generate pattern-based workloads.
Synchronous APIs work in scripts and notebooks; async APIs remain available.
Research algorithms and experiment tracking stay in separate projects.

Start with [installation](docs/installation.md) and the [quickstart](docs/quickstart.md),
or browse the [documentation overview](docs/index.md).

## Start developing

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer. From this directory:

```sh
uv sync --locked
uv run python -c "import bondi; print(bondi.__file__)"
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`uv sync` installs the package in editable mode and includes the development group.
PyMongo is a required dependency for BSON support; no database service is needed.
The committed `uv.lock` records the development dependency resolution.

[Documentation](https://relaxed-constraints.github.io/bondi/) ·
[Issues](https://github.com/relaxed-constraints/bondi/issues) · [MIT license](LICENSE)

## Read the documentation

Start with [the documentation overview](docs/index.md),
[architecture decisions](docs/architecture.md), and
[the implementation roadmap](docs/roadmap.md).

To preview or validate the documentation site:

```sh
uv sync --locked --group docs
uv run --group docs mkdocs serve
# Or build without starting a server:
uv run --group docs mkdocs build --strict
```

API reference pages are generated from Python docstrings using mkdocstrings.
Tutorials are available in `notebooks/workload_demo.ipynb` (MongoDB) and
`notebooks/couchbase_demo.ipynb` (Couchbase).
For database-independent inference and inspection, see the [schema guide](docs/schemas.md)
and `notebooks/schema_demo.ipynb`.

## Repository layout

```text
src/bondi/     Installable library
tests/            Offline tests
docs/             Getting started, guides, tutorials, API reference and development
```

See [the contributor guide](docs/contributing.md) for the development workflow.
A distribution can be built with `uv build`.

## Publication

BONDI is MIT licensed, copyright Relaxed Constraints. Version [0.1.0](https://pypi.org/project/bondi/0.1.0/) is available on PyPI.
Install with `uv add bondi` or `pip install bondi`; use `bondi[couchbase]` for the optional SDK.
Get notebooks and Docker files from the matching GitHub release source.
See [release preparation](docs/releases.md) for the publishing process.

## Optional local databases

See [the local database guide](docs/local-databases.md) for MongoDB and Couchbase
Docker Compose profiles, sample data, startup and cleanup. No database or Docker
installation is required for the offline test suite.
