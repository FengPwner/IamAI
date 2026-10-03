"""Every file in snippets/ must actually pass its own doctests.

The writer adds one snippet per round. A snippet whose doctest lies is worse than
no snippet, so this test scans whatever is in the directory at the time it runs --
empty directory is fine, a broken example is not.
"""

from __future__ import annotations

import doctest
from pathlib import Path

import pytest

SNIPPETS = Path(__file__).resolve().parent.parent / "snippets"

files = sorted(SNIPPETS.glob("*.py")) if SNIPPETS.exists() else []


@pytest.mark.parametrize("path", files, ids=lambda p: p.name)
def test_snippet_doctests(path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"snippet_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    import inspect

    funcs = [o for _, o in vars(module).items() if inspect.isclass(o) or inspect.isfunction(o)]
    results = doctest.testmod(module, verbose=False, raise_on_error=True)
    assert results.attempted >= 0
    assert funcs, f"{path.name} defines nothing"
