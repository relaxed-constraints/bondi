# Installation

Use Python **3.11 or newer** and `uv`. Work from a checkout of this repository;
the instructions below do not assume a published PyPI release.

```sh
git clone https://github.com/relaxed-constraints/bondi.git
cd bondi
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
uv add --editable /path/to/bondi
# Include the optional backend if needed:
uv add --editable '/path/to/bondi[couchbase]'
```

## Notebooks

From the toolkit checkout, launch Jupyter using the same environment as the package:

```sh
uv run --with jupyterlab --with ipykernel jupyter lab
```

Open a notebook under `notebooks/` and choose the Python kernel from this environment.
The guides use synchronous APIs: no `await` or event-loop setup is needed in notebooks.

To preview this documentation, see [Building the documentation](documentation.md).

## Library versus teaching resources

PyPI publication is pending. Once 0.1.0 is published, library-only users will be
able to use `uv add bondi` or `pip install bondi` (add `[couchbase]` for the SDK).
Until then, use the checkout instructions above.

Notebooks, Docker Compose files and demo data live in the GitHub repository, not
inside the installed Python package. Clone the repository to obtain them, or download
the source archive from a [GitHub release](https://github.com/relaxed-constraints/bondi/releases).
After a release is published, use its matching tag (for example `git checkout v0.1.0`)
and run `uv sync --locked` from that checkout. Archives work too and do not require Git.
