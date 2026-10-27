# Installation

BONDI **0.1.1** is available on [PyPI](https://pypi.org/project/bondi/0.1.1/).
Use Python **3.11 or newer**. Choose a library installation for your own project,
or a source checkout for notebooks and local demo databases.

## Install the Python library

In an existing uv project:

```sh
uv add bondi
# Include the optional Couchbase SDK when needed:
uv add 'bondi[couchbase]'
```

Or, in an activated Python virtual environment:

```sh
python -m pip install bondi
python -m pip install 'bondi[couchbase]'
```

PyMongo and its BSON codecs are installed automatically. Couchbase query descriptions
and offline parsing work without the optional SDK; executing Couchbase queries needs it.
For reproducible experiments, pin the release (`bondi==0.1.1`) and retain your project's
lockfile. The API is still evolving.

Verify installation with `uv run python` in a uv project, or `python` in your
activated environment:

```sh
python -c "from importlib.metadata import version; import bondi; print(version('bondi'))"
```

Query construction, schema inspection and saved-response parsing need no database.
Continue with the [quickstart](quickstart.md) for an offline example and a database query.

## Get notebooks and Docker Compose files

Teaching resources are included in the GitHub source, not in the installed wheel.
Clone the matching release:

```sh
git clone --branch v0.1.1 https://github.com/relaxed-constraints/bondi.git
cd bondi
uv sync --locked
# If you want to execute Couchbase queries:
uv sync --locked --extra couchbase
```

Alternatively, download and extract a source archive from the
[0.1.1 GitHub release](https://github.com/relaxed-constraints/bondi/releases/tag/v0.1.1),
then run `uv sync --locked` in the extracted folder. Git is not required for archives.
Both options provide `notebooks/`, Compose files, initialization scripts and demo data.
Use [Local databases](local-databases.md) to start and initialize a backend.

## Open the notebooks

From the source checkout or extracted release:

```sh
uv run --with jupyterlab --with ipykernel jupyter lab
```

Choose the Python kernel from this environment and open a notebook under `notebooks/`.
Examples use synchronous APIs: no `await` or event-loop setup is needed.

## Develop BONDI

To work on current development code, clone the default branch without `--branch`,
then follow [Contributing](contributing.md). Use an editable checkout dependency
only when you intentionally want local source changes in another project:

```sh
uv add --editable /path/to/bondi
```

See [Building the documentation](documentation.md) to preview the site locally.
