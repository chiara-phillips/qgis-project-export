"""Import-smoke tests that verify every plugin module loads under PyQt6.

This catches short-form Qt enum regressions (for example ``Qt.AlignCenter``
instead of ``Qt.AlignmentFlag.AlignCenter``) which raise ``AttributeError`` in
PyQt6 during class-body evaluation.
"""

import importlib
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "project_export"

if not (PLUGIN_ROOT / "metadata.txt").is_file():
    raise RuntimeError(
        f"Expected plugin package at {PLUGIN_ROOT} (metadata.txt not found)."
    )


def _module_names():
    """Yield dotted module names for every .py file under the plugin package."""
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        rel = path.relative_to(PLUGIN_ROOT.parent).with_suffix("")
        parts = rel.parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        yield ".".join(parts)


@pytest.mark.parametrize("module_name", list(_module_names()))
def test_module_imports_under_pyqt6(module_name):
    """Each plugin module must import cleanly when qgis.PyQt maps to PyQt6."""
    importlib.import_module(module_name)
