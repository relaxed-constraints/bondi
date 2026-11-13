---
name: bondi
description: Use BONDI's Python API and CLI for document database deployments, native queries, workloads, execution, schema inspection, MongoDB estimation and generation. Also use when developing BONDI itself. Keep research algorithms and experiment pipelines in consumer projects.
---

# BONDI

Help students and researchers use the toolkit and understand the building blocks
they are combining. BONDI preserves native MongoDB queries and Couchbase SQL++;
it is not a query translator or an experiment-tracking framework.

## Choose the workflow

- For library or CLI usage, read [API and CLI](references/api-and-cli.md).
- To find explanations, API contracts or runnable examples, use the
  [documentation and tutorial map](references/documentation-and-tutorials.md).
- Only when changing BONDI itself, read [development](references/development.md).
  Do not apply BONDI's contributor workflow to a student's consumer repository.

Check the project's installed version (for example,
`uv run python -c "from importlib.metadata import version; print(version('bondi'))"`)
and dependency constraints before using an API. This skill describes the 0.2.0 API.
It includes sustained load generation, pattern selection, workload callbacks,
MongoDB memory limits and executor health checks. Check installed signatures before
using these features. Online documentation can be newer than the installed package.
Inspect matching source when versions differ. Do not upgrade silently.
An installed skill contains these references, not the BONDI checkout or notebooks.

## Teach while helping

Explain the purpose of the BONDI component or important option being used, briefly
and in the context of the user's task. Provide a relevant clickable online guide
or API reference link where it helps the user understand, verify or extend the
solution. Prefer a specific page (and a verified object anchor when useful) over
the documentation homepage. Use the documentation map for real URLs.

For example, when using `collect_results=True`, explain that executors consume
all rows anyway and this option retains the documents, then link to the
[execution guide](https://relaxed-constraints.github.io/bondi/executor/).
When introducing sampling, explain the distinction between estimated matches and
full-population guarantees and link to the estimation guide.

Offer the matching tutorial notebook when the user wants to explore further.
Keep explanations proportional to their experience and request: a short reason
and one or two useful links usually suffice. Do the requested work; do not replace
it with reading assignments, dump every reference, or require a lesson before
proceeding. If working offline, you may supply known links but do not claim to have
verified their current contents. State version differences when material.

## Preserve the toolkit's boundaries

Use synchronous examples by default for teaching and notebooks; use asynchronous
APIs when the application needs them. Keep query forms native, workloads ordered
and single-backend, and missing diagnostic metrics unknown rather than zero.
Keep research algorithms, benchmark orchestration and experiment tracking in
consumer projects. Consult the current roadmap before assuming a capability exists.

## Sustained load generation

Version 0.2.0 adds executor `generate_load()` with `bondi.load` policies
`WeightedRandom`, `UniformRandom`, `Sequential` and `ByPattern`.
`ByPattern` selects a pattern ID, then an existing query instance within that pattern. Check the installed release
before using it. It inherits executor concurrency/error/health options; selection
and positive measurement/drain durations are required. Warm-up defaults to zero.
`on_result` receives one `LoadResult`; `collect_results` retains database documents,
while `return_load_results=False` streams observations without retaining their list.
Drain expiry records unresolved results and requests cooperative cancellation;
no hard process deadline or server-side cancellation guarantee is provided.
See `docs/load-generation.md` in the source checkout.

## Dataset loading (unreleased)

Use `load_file`, `load_documents`, `load_hf_dataset` or `load_hf_repository`
from `bondi.data`. Single-source calls require an exact CollectionRef.
Hub calls combine all splits by default; select a split explicitly when needed.
Sources can be files, Hub datasets or document iterables. Use a namespace when anonymous sources lack IDs.
Create mode refuses nonempty collections. Replacement explicitly permits clearing the selected collection.
Do not change a user's write mode to bypass a refusal. Report partial writes if a load fails.
See `docs/datasets.md` and `notebooks/dataset_loading.ipynb` in the source checkout.

## CLI command groups

Use `bondi deployment create` to create a deployment. Use
`bondi deployment list|status|start|stop|logs|remove` to manage deployments.
Use `bondi dataset` for dataset commands. The Python API is unchanged.
