# Building the documentation

There are two complementary sources of documentation:

- Hand-written Markdown explains concepts and workflows, such as the
  [MongoDB query guide](find-query.md).
- Python docstrings describe public API contracts. mkdocstrings extracts these
  into the [API reference](api.md).

## 1. Write the contract beside the code

Open `src/bondi/mongodb/collection.py`. The class docstring contains a summary,
behavioural details, and Google-style sections. The constructor signature comes
from the dataclass fields and their type hints. The `from_namespace` factory
documents its inputs, output, and errors in `Args`, `Returns`, and `Raises`.

For methods and functions that return a value, use a return annotation and a
short `Returns` description that explains what the caller receives. The
reference displays annotations and links documented BONDI types automatically.
When an annotation is `Self`, link to the concrete class in the description.

The docstring is the source of truth for the API contract; avoid maintaining a
second copy of its parameter descriptions in Markdown.

## 2. Place the API in a Markdown page

`docs/reference/mongodb/queries.md` contains this directive:

```text
::: bondi.mongodb.MongoCollectionRef
```

The mkdocstrings plugin resolves that public Python path and renders the class
signature and docstring. The re-export in `mongodb/__init__.py` provides the same
public path students use in Python. API pages must explicitly select the objects
we want to document; new classes are not automatically added to navigation.

## 3. Configure the site

`mkdocs.yml` defines project metadata, navigation, API source paths and Markdown-export
sections. It inherits shared theme, Markdown-extension and API-rendering defaults
from `.relcon-docs/base.yml`, managed by
[relcon-docs](https://github.com/relaxed-constraints/relcon-docs). Both files are
checked into this repository. Installing dependencies does not regenerate them.
`paths: [src]` tells the handler where our package lives, and
`docstring_style: google` selects the docstring convention.
The Python handler puts signatures in separate code blocks and links documented
types. Ruff formats long signatures. The `docs` dependency group supplies the
shared tooling package, which supplies the site builder, Python handler, and formatter.
It is a documentation dependency: ordinary BONDI installations do not install it.
Until a PyPI release is adopted, the group pins relcon-docs to an exact Git commit;
installation requires Git but no local checkout of that repository.

### Shared defaults and project overrides

Keep BONDI-specific settings in `mkdocs.yml`. Do not edit the managed
`.relcon-docs/base.yml`, `docs/stylesheets/relcon-docs.css` or
`.relcon-docs/state.json` files. The state file records the applied package version
and asset hashes so the tool can detect manual changes.

When upgrading relcon-docs, update the pinned Git revision in `pyproject.toml`,
refresh `uv.lock` with `uv lock`, and install the updated docs group. Then review
and apply its configuration changes:

```sh
uv run --group docs relcon-docs configure --dry-run
uv run --group docs relcon-docs configure
uv run --group docs relcon-docs configure --check
uv run --group docs zensical build --strict
```

For pip, run the same commands without `uv run --group docs` after installing
the docs group. Commit the dependency and generated-file changes together.
Configuration conflicts stop the update without writing files. Move customizations
to project overrides or a separate stylesheet; `--force` explicitly replaces
conflicting managed files and should only be used after reviewing the diff.
CI checks that managed files match the installed package.

Zensical merges inherited mappings recursively; project values override defaults.
Lists replace inherited lists rather than extending them. Plugins and Markdown
extensions use mapping syntax so a project can override one setting without
dropping unrelated defaults. Paths are resolved relative to the root configuration.

The `llmstxt` configuration generates `llms.txt` and per-page Markdown exports;
the inherited `content.action.copy` feature and CSS provide the labeled copy button.
The YAML filename does not change the builder: continue using Zensical commands.

## 4. Preview locally

Run from the repository root. For pip, use the activated virtual environment from
[Contributing](contributing.md#setup).

=== "uv"

    ```sh
    uv sync --locked --group docs
    uv run --group docs zensical serve
    ```

=== "pip"

    ```sh
    python -m pip install --group docs
    zensical serve
    ```

Open the preview URL printed in the terminal. Change a sentence in the class docstring and save it;
the preview rebuilds. Stop the server with Ctrl+C.

## 5. Verify before sharing

=== "uv"

    ```sh
    uv run --group docs zensical build --strict
    uv run pytest
    ```

=== "pip"

    ```sh
    zensical build --strict
    python -m pytest
    ```

Zensical writes static HTML into the ignored `site/` directory. Strict mode fails
on documentation warnings, such as broken local links or unresolved API objects.
It does not prove the examples are correct or execute ordinary Markdown code
blocks. Pytest runs our contract tests and, with the configured `--doctest-modules`
option, the `>>>` examples in the Python source.

Building is local; it does not publish the documentation. Hosting can be chosen
later.


## Documentation theme

The site uses Zensical’s modern theme.
Shared theme settings come from relcon-docs through `.relcon-docs/base.yml`.
Project overrides belong in `mkdocs.yml`. Top-level tabs separate onboarding, guides, tutorials, reference and development.
Code-copy buttons are enabled. `font: false` uses system fonts without fetching Google Fonts.

After a dependency or theme change, [restart the preview server](#4-preview-locally).

The theme affects documentation only; installing the toolkit does not install it.
