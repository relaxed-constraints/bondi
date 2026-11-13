# Installation

Install BONDI **0.3.0** from [PyPI](https://pypi.org/project/bondi/0.3.0/).
Use Python **3.11 or newer**. Choose a library installation for your own project,
or a source checkout for notebooks and local demo databases.

## Install the Python library

Choose the base install for MongoDB support or include the Couchbase extra
if you need to execute Couchbase queries.

=== "uv"

    In an existing uv project:

    ```sh
    # MongoDB support
    uv add bondi

    # Include the optional Couchbase SDK
    uv add 'bondi[couchbase]'
    ```

=== "pip"

    In an activated Python virtual environment:

    ```sh
    # MongoDB support
    python -m pip install bondi

    # Include the optional Couchbase SDK
    python -m pip install 'bondi[couchbase]'
    ```

PyMongo and its BSON codecs are installed automatically. Couchbase query descriptions
and offline parsing work without the optional SDK; executing Couchbase queries needs it.
For reproducible experiments, pin the release (`bondi==0.3.0`) and retain your project's
lockfile. The API is still evolving.


## Get notebooks and demo data

Educational Jupyter notebooks are included in the GitHub source, not in the installed wheel.
Clone the matching release:

```sh
git clone --branch v0.3.0 https://github.com/relaxed-constraints/bondi.git
cd bondi
```

Alternatively, download and extract a source archive from the
[0.3.0 GitHub release](https://github.com/relaxed-constraints/bondi/releases/tag/v0.3.0),
and open a terminal in the extracted folder. Git is only needed for cloning.
Both options provide `notebooks/` and demo data.

From the source directory, set up an environment using either tool. In the pip
examples, activate it with `.venv\Scripts\Activate.ps1` on Windows PowerShell
in place of the `source` command.

=== "uv"

    ```sh
    uv sync --locked
    # For Couchbase notebooks, use:
    uv sync --locked --extra couchbase
    ```

=== "pip"

    ```sh
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install -e .
    # For Couchbase notebooks, use:
    python -m pip install -e ".[couchbase]"
    ```

The uv commands use the repository lockfile. The pip commands resolve dependencies
from the checkout’s package metadata.
Use the CLI or Python API in [Database deployment](deployment.md) to start a backend.
Deployments start empty; load the data needed by your examples separately.

## Open the notebooks

From the source directory, use the environment set up above. For pip, keep that
virtual environment activated.

=== "uv"

    ```sh
    uv run --with jupyterlab --with ipykernel jupyter lab
    ```

=== "pip"

    ```sh
    python -m pip install jupyterlab ipykernel
    python -m jupyterlab
    ```

If you set up Couchbase support with uv, include `--extra couchbase` in the
`uv run` command.

Choose the Python kernel from this environment and open a notebook under `notebooks/`.


## Develop BONDI

To work on current development code, clone the default branch without `--branch`,
then follow [Contributing](contributing.md). Use an editable checkout dependency
only when you intentionally want local source changes in another project:

=== "uv"

    ```sh
    uv add --editable /path/to/bondi
    ```

=== "pip"

    In an activated Python virtual environment:

    ```sh
    python -m pip install --editable /path/to/bondi
    ```

See [Building the documentation](documentation.md) to preview the site locally.
