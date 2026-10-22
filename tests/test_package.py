"""Verify that the installed distribution and importable package agree."""

from importlib.metadata import distribution
from pathlib import Path

import dbrtoolkit


def test_installed_package():
    package = distribution("dbrtoolkit")
    assert package.metadata["Name"] == "dbrtoolkit"
    assert dbrtoolkit.__file__ is not None
    assert Path(dbrtoolkit.__file__).is_file()
