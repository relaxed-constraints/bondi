"""Check that project overrides retain inherited documentation capabilities."""

from pathlib import Path

import pytest

zensical_config = pytest.importorskip("zensical.config")


def test_project_overrides_preserve_shared_documentation_defaults():
    root = Path(__file__).resolve().parents[1]
    config = zensical_config.parse_config(str(root / "mkdocs.yml"))

    # Local source paths must not replace the inherited API-rendering options.
    assert "admonition" in config["markdown_extensions"]
    assert "pymdownx.details" in config["markdown_extensions"]
    fences = config["mdx_configs"]["pymdownx.superfences"]["custom_fences"]
    assert any(fence["name"] == "mermaid" for fence in fences)
    python = config["plugins"]["mkdocstrings"]["config"]["handlers"]["python"]
    assert python["paths"] == ["src"]
    assert python["options"]["signature_crossrefs"] is True
    assert python["options"]["docstring_style"] == "google"

    # Adding local Markdown-export sections must retain search and the copy UI.
    assert config["plugins"]["search"]["config"]["enabled"] is True
    sections = config["plugins"]["llmstxt"]["config"]["sections"]
    api_section = next(section for section in sections if section["title"] == "API reference")
    assert api_section["inputs"][0]["pattern"] == "reference/**/*.md"
    assert "content.action.copy" in config["theme"]["features"]
    assert config["theme"]["variant"] == "modern"


def test_managed_documentation_files_match_installed_package():
    cli = pytest.importorskip("relcon_docs.cli")
    root = Path(__file__).resolve().parents[1]
    assert cli.main(["configure", "--project", str(root), "--check"]) == 0


def test_deployment_is_limited_to_published_releases_and_manual_requests():
    yaml = pytest.importorskip("yaml")
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load((root / ".github/workflows/docs.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"] == {
        "release": {"types": ["published"]},
        "workflow_dispatch": "",
    }
    assert not (root / ".github/workflows/pages.yml").exists()
    assert workflow["permissions"]["pages"] == "write"
    assert workflow["permissions"]["id-token"] == "write"


def test_version_macros_follow_source_metadata(tmp_path):
    import runpy
    from types import SimpleNamespace

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(str(root / "scripts/docs_macros.py"))
    define_env = namespace["define_env"]
    # Simulate a future source release without installing a matching distribution.
    define_env.__globals__["__file__"] = str(tmp_path / "scripts/docs_macros.py")
    metadata = tmp_path / "pyproject.toml"
    for version in ["0.3.6", "9.8.7"]:
        metadata.write_text(f'[project]\nversion = "{version}"\n')
        env = SimpleNamespace(variables={})
        define_env(env)
        assert env.variables["bondi_version"] == version


def test_current_release_pages_use_version_variable():
    import re

    root = Path(__file__).resolve().parents[1]
    config = zensical_config.parse_config(str(root / "mkdocs.yml"))
    macros = config["mdx_configs"]["zensical.extensions.macros"]
    assert macros["module_name"] == "scripts/docs_macros"
    assert macros["render_by_default"] is False
    assert macros["on_error_fail"] is True
    for name in ["index.md", "installation.md"]:
        source = (root / "docs" / name).read_text()
        assert "render_macros: true" in source
        assert "{{ bondi_version }}" in source
        assert not re.search(r"\b0\.\d+\.\d+\b", source)
