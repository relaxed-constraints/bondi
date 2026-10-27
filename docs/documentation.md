# Building the documentation

There are two complementary sources of documentation:

- Hand-written Markdown explains concepts and workflows, such as the
  [MongoDB query guide](find-query.md).
- Python docstrings describe public API contracts. mkdocstrings extracts these
  into the [API reference](api.md).

## 1. Write the contract beside the code

Open `src/dbrtoolkit/mongodb/collection.py`. The class docstring contains a summary,
behavioural details, and Google-style `Args`, `Raises`, and `Examples` sections.
The constructor signature comes from the dataclass fields and their type hints.

The docstring is the source of truth for the API contract; avoid maintaining a
second copy of its parameter descriptions in Markdown.

## 2. Place the API in a Markdown page

`docs/reference/mongodb/queries.md` contains this directive:

```text
::: dbrtoolkit.mongodb.MongoCollectionRef
```

The mkdocstrings plugin resolves that public Python path and renders the class
signature and docstring. The re-export in `mongodb/__init__.py` provides the same
public path students use in Python. API pages must explicitly select the objects
we want to document; new classes are not automatically added to navigation.

## 3. Configure the site

`mkdocs.yml` defines navigation and enables mkdocstrings with the Python handler.
`paths: [src]` tells the handler where our package lives, and
`docstring_style: google` selects the docstring convention.
The `watch: [src]` setting makes source edits trigger a preview rebuild as well as
Markdown edits. Documentation dependencies are in the `docs` dependency group,
not the library's runtime dependencies.

## 4. Preview locally

From the repository root:

```sh
uv sync --locked --group docs
uv run --group docs mkdocs serve
```

Open <http://127.0.0.1:8000/>. Change a sentence in the class docstring and save it;
the preview rebuilds. Stop the server with Ctrl+C.

## 5. Verify before sharing

```sh
uv run --group docs mkdocs build --strict
uv run pytest
```

MkDocs writes static HTML into the ignored `site/` directory. Strict mode fails
on documentation warnings, such as broken local links or unresolved API objects.
It does not prove the examples are correct or execute ordinary Markdown code
blocks. Pytest runs our contract tests and, with the configured `--doctest-modules`
option, the `>>>` examples in the Python source.

Building is local; it does not publish the documentation. Hosting can be chosen
later.


## Documentation theme

The site uses Material for MkDocs, installed through the `docs` dependency group.
Theme settings live in `mkdocs.yml`. Top-level tabs separate onboarding, guides, tutorials, reference and development.
Code-copy buttons are enabled. `font: false` uses system fonts without fetching Google Fonts.

After a dependency or theme change, restart the local server:

```sh
uv run --group docs mkdocs serve
```

The theme affects documentation only; installing the toolkit does not install it.
