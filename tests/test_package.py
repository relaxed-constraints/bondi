"""Verify that the installed distribution and importable package agree."""

from importlib.metadata import distribution
from pathlib import Path

import bondi


def test_installed_package():
    package = distribution("bondi")
    assert package.metadata["Name"] == "bondi"
    assert bondi.__file__ is not None
    assert Path(bondi.__file__).is_file()
