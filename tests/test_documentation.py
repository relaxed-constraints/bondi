"""Check that project overrides retain inherited documentation capabilities."""

from pathlib import Path

import pytest

zensical_config = pytest.importorskip("zensical.config")


def test_project_overrides_preserve_shared_documentation_defaults():
    root = Path(__file__).resolve().parents[1]
    config = zensical_config.parse_config(str(root / "mkdocs.yml"))

    # Local source paths must not replace the inherited API-rendering options.
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
