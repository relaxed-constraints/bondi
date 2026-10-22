# Contributing

## Setup

Install uv, then run from the repository root:

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Python 3.11 is the minimum supported version and the local development default.
There are no sibling-repository dependencies or database prerequisites.

## Making a change

Keep each change small enough to explain and review as a whole. Discuss the public
contract before adding a component. Document public behaviour with Google-style
docstrings, including important constraints and examples. Add focused tests for
behaviour rather than mirroring implementation details.

```sh
uv run ruff format .
uv run ruff check .
uv run pytest
uv sync --locked --group docs
uv run --group docs mkdocs build --strict
uv build
```

Commit `uv.lock` when dependencies change. Generated files under `site/` and
`dist/` stay outside version control. Keep credentials in local ignored files;
never put them in examples, workload artifacts or experiment parameters.

## Documentation and tutorials

Maintain the architecture and roadmap as decisions are made. API documentation is
rendered from source docstrings. Add short, executable tutorial notebooks once a
complete workflow exists; exploratory notebooks belong in research repositories.

## Test boundaries

The current suite checks package installation/import, collection-reference contracts
and Python docstring examples. Unit tests should remain database-independent. Live backend tests will require explicit opt-in and
isolated test data when those backends are introduced.

See the [documentation walkthrough](documentation.md) for a concrete docstring-to-site example.
