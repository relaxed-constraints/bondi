# Installation

Use Python **3.11 or newer** and `uv`. Work from a checkout of this repository;
the instructions below do not assume a published PyPI release.

```sh
cd /path/to/dbrtoolkit
uv sync --locked
```

PyMongo is required and installed automatically, including its BSON codecs.
Install the optional SDK if you want to execute Couchbase queries:

```sh
uv sync --locked --extra couchbase
```

Query objects, schemas, workload persistence and offline summary parsing do not
require a running database. For execution, follow [Local databases](local-databases.md).

## Use the toolkit in another project

From your research project's directory, add your local checkout as an editable dependency:

```sh
uv add --editable /path/to/dbrtoolkit
# Include the optional backend if needed:
uv add --editable '/path/to/dbrtoolkit[couchbase]'
```

## Notebooks

From the toolkit checkout, launch Jupyter using the same environment as the package:

```sh
uv run --with jupyterlab --with ipykernel jupyter lab
```

Open a notebook under `notebooks/` and choose the Python kernel from this environment.
The guides use synchronous APIs: no `await` or event-loop setup is needed in notebooks.

To preview this documentation, see [Building the documentation](documentation.md).
