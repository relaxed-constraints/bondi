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

### Serve the documentation locally

From the repository root, run:

```sh
uv run --group docs mkdocs serve
```

Open <http://127.0.0.1:8000/bondi/>. The preview reloads when you save changes to
Markdown or Python docstrings. Stop the server with Ctrl+C.

See [Building the documentation](documentation.md#4-preview-locally) for more details.

## Test boundaries

The offline suite checks query contracts, persistence, parsers and executor behavior
at SDK boundaries. Run `uv run --extra couchbase pytest` to include Couchbase SDK
tests; they are skipped without the optional dependency. Live backend tests require
explicit environment-variable opt-in. See the local database guide for setup; Couchbase
checks use read-only queries against the initialized Compose demo data.

See the [documentation walkthrough](documentation.md) for a concrete docstring-to-site example.

## Feature branches

Implement new features on a `codex/` feature branch. After verification, commit the
feature and merge it back into `main`, preserving unrelated user changes.

## Documentation organization

Keep onboarding short and executable, guides focused on common tasks, and detailed
contracts in source docstrings and reference pages. Use synchronous examples by
default. Tutorials point to the maintained notebooks rather than duplicating their
contents. Every public API object should have one reference home. Update navigation
and local links when moving a page; execute changed examples as well as building
the site.
