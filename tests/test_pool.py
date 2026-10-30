"""Every snippet in the pool must pass its own doctests *before* it can be used.

The writer is only allowed to add a snippet by taking one from iamai/pool.py, so a
wrong example in that pool is a bug the loop will happily reproduce forever. The
older test only covered snippets already written to disk, which meant a broken
example sat in the pool until the writer happened to reach it and poison a commit.
"""

from __future__ import annotations

import doctest
import importlib.util
import inspect
import tempfile
from pathlib import Path

import pytest

from iamai import pool


def _load(name: str, code: str):
    """Exec a pool module from a temp file so relative imports behave."""

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_text(code, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(f"pool_{Path(name).stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


@pytest.mark.parametrize(
    "entry", pool.SNIPPETS, ids=lambda e: e[0]
)
def test_pool_entry_shape(entry):
    name, code = entry
    assert name.endswith(".py")
    assert code.strip(), f"{name} is empty"
    assert not (Path(name).name != name), f"{name} must be a bare filename"


@pytest.mark.parametrize("entry", pool.SNIPPETS, ids=lambda e: e[0])
def test_pool_entry_doctests_pass(entry):
    name, code = entry
    module = _load(name, code)
    results = doctest.testmod(module, verbose=False)
    assert results.failed == 0, f"{name}: {results.failed} of {results.attempted} doctests failed"
    assert results.attempted > 0, f"{name} has no examples to check itself against"


@pytest.mark.parametrize("entry", pool.SNIPPETS, ids=lambda e: e[0])
def test_pool_entry_defines_something(entry):
    name, code = entry
    module = _load(name, code)
    members = [o for _, o in vars(module).items() if inspect.isclass(o) or inspect.isfunction(o)]
    assert members, f"{name} defines no functions or classes"


def test_take_and_remaining_agree_with_the_pool():
    assert pool.take(0)[0] == pool.SNIPPETS[0][0]
    assert pool.take(len(pool.SNIPPETS)) is None
    assert pool.take(-1) is None
    assert pool.remaining(0) == len(pool.SNIPPETS)
    assert pool.remaining(len(pool.SNIPPETS)) == 0
