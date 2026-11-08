"""Verify the installed package's import and metadata contract."""

from importlib.metadata import version

import forgeflow


def test_package_import_has_version() -> None:
    assert forgeflow.__version__


def test_package_version_matches_distribution() -> None:
    assert forgeflow.__version__ == version("forgeflow")
