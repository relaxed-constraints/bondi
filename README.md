# Database Research Toolkit

**dbrtoolkit** provides Python building blocks for reproducible database research.

The planned scope includes native queries, workloads, schema inference, workload
generation, database execution, explain parsing and index management. Research
algorithms and experiment pipelines live in separate repositories that depend on
this toolkit.

**Status:** foundation and `MongoCollectionRef` implemented. No database connections
or query execution are implemented yet. See the [first example](docs/collection-reference.md).

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
There are no runtime dependencies and no database service is needed for these checks.
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
Tutorial notebooks will be added when there is a coherent working example.

## Repository layout

```text
src/dbrtoolkit/     Installable library
tests/            Offline tests
docs/             Architecture, roadmap, contributor guide and API reference
```

See [the contributor guide](docs/contributing.md) for the development workflow.
A distribution can be built with `uv build`.

## Publication

This is a local, unpublished project. A license and release policy must be chosen
before public distribution; no license is implied by this scaffold.
