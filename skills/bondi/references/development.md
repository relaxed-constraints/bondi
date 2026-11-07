# Developing BONDI

Use this workflow only when the task changes BONDI itself. Work in its source
checkout and read its current `AGENTS.md`, `docs/architecture.md` and
`docs/roadmap.md` first. Repository instructions take precedence over this snapshot.

Discuss new public contracts before implementation. Keep changes small and
student-readable, runtime dependencies minimal, and research algorithms and
experiment pipelines downstream. Do not depend on sibling checkouts.
Use the `Mongo` class prefix for MongoDB implementations, retaining the
`mongodb` module name. Inspect and preserve unrelated edits. The repository
workflow uses a `codex/` feature branch, then commits and merges to `main`
after checks pass; it does not imply pushing or publishing a release.

## Code and verification

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run --group docs mkdocs build --strict
uv build
```

Add focused behavior tests for changed contracts, not tests that merely mirror
implementation. Pytest also executes source doctests. Use
`uv run --extra couchbase pytest` when optional SDK coverage matters.
Offline tests do not prove live database behavior. With Docker running, use
`BONDI_LIVE=1 uv run --extra couchbase pytest -m live -v`. Shared fixtures create isolated BONDI deployments, load demo data
and indexes, and remove their own resources. They use MongoDB ports 27117–27126
and Couchbase groups starting at 8191/8193/11310, stepping by ten for ten groups.
Do not supply private research server URIs; old per-suite flags are no longer used.
Run live tests serially. See the release guide for port pools and cleanup details.

Keep `uv.lock` updated when dependencies change. Generated `site/` and `dist/`
are not committed. Credentials belong in ignored local configuration.

[Contributing](https://relaxed-constraints.github.io/bondi/contributing/)

## Documentation and teaching

Maintain Google-style public docstrings as the API contract, guide pages for
workflows, and explicit mkdocstrings entries under `docs/reference/`. Update
`mkdocs.yml` navigation when adding pages. Keep runnable tutorials under
`notebooks/` and research exploration in consumer repositories.

Preview with `uv run --group docs mkdocs serve`; follow its printed local URL.
A strict build checks documentation structure, not ordinary Markdown examples.
Execute changed examples where feasible and report whether live examples ran.
Update this skill when public behavior changes, especially CLI lifecycle semantics,
supported capabilities and links.

[Documentation walkthrough](https://relaxed-constraints.github.io/bondi/documentation/)

## Build versus release

`uv build` creates local distributions; it does not publish them.
For a requested release, follow the current `docs/releases.md` and
`.github/workflows/release.yml`, including offline and live validation.
Update package version/changelog, verify tag/version agreement, and use a new
version rather than replacing a published artifact. Publishing a GitHub release
triggers CI and PyPI publication through trusted publishing; GitHub Pages also
builds on published releases. A skill installation or ordinary code-change request
is not authorization to publish.

Review skill examples against the release API and keep the skill available in
tagged GitHub source. Skill installation is separate from Python package installation.
Do not claim an older tag includes a newly added skill.

[Release procedure](https://relaxed-constraints.github.io/bondi/releases/)
