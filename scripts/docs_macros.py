"""Expose the source package version to selected documentation pages."""

import tomllib
from pathlib import Path


def define_env(env):
    """Read source metadata, independent of the installed BONDI version."""
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as source:
        env.variables["bondi_version"] = tomllib.load(source)["project"]["version"]
