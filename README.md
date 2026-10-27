# Database Research Toolkit

**dbrtoolkit** provides Python building blocks for reproducible database research.

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
uv run python -c "import dbrtoolkit; print(dbrtoolkit.__file__)"
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`uv sync` installs the package in editable mode and includes the development group.
PyMongo is a required dependency for BSON support; no database service is needed.
The committed `uv.lock` records the development dependency resolution.

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
src/dbrtoolkit/     Installable library
tests/            Offline tests
docs/             Getting started, guides, tutorials, API reference and development
```

See [the contributor guide](docs/contributing.md) for the development workflow.
A distribution can be built with `uv build`.

## Publication

This is a local, unpublished project. A license and release policy must be chosen
before public distribution; no license is implied by this scaffold.

## Optional local databases

See [the local database guide](docs/local-databases.md) for MongoDB and Couchbase
Docker Compose profiles, sample data, startup and cleanup. No database or Docker
installation is required for the offline test suite.
