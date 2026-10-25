"""Tests for snippets/checkpoint.py — atomic progress checkpoints."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from checkpoint import Checkpoint  # noqa: E402


@pytest.fixture
def cp_path(tmp_path: Path) -> Path:
    return tmp_path / "progress.json"


# ---- save / load round-trip ----


def test_save_and_load(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({"stroke": 100, "file": "notes/x.md"})
    loaded = cp.load()
    assert loaded == {"stroke": 100, "file": "notes/x.md"}


def test_load_returns_none_when_missing(cp_path: Path):
    cp = Checkpoint(cp_path)
    assert cp.load() is None


def test_overwrite_preserves_latest(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({"v": 1})
    cp.save({"v": 2})
    assert cp.load()["v"] == 2


def test_save_rejects_non_dict(cp_path: Path):
    cp = Checkpoint(cp_path)
    with pytest.raises(TypeError):
        cp.save([1, 2, 3])  # type: ignore[arg-type]


def test_unicode_roundtrip(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({"msg": "深夜巡房第十四次", "emoji": "🌙"})
    loaded = cp.load()
    assert loaded["msg"] == "深夜巡房第十四次"
    assert loaded["emoji"] == "🌙"


# ---- integrity / corruption ----


def test_corrupted_file_returns_none(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({"stroke": 42})

    # tamper with the file
    raw = cp_path.read_text()
    tampered = raw.replace('"stroke": 42', '"stroke": 99')
    cp_path.write_text(tampered)

    assert cp.load() is None


def test_missing_digest_returns_none(cp_path: Path):
    cp_path.write_text(json.dumps({"data": {"x": 1}, "ts": 0}))
    cp = Checkpoint(cp_path)
    assert cp.load() is None


def test_truncated_json_returns_none(cp_path: Path):
    cp_path.write_text('{"ts": 1, "data": {"x":')
    cp = Checkpoint(cp_path)
    assert cp.load() is None


# ---- age ----


def test_age_is_recent(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({"ok": True})
    assert cp.age() is not None
    assert cp.age() < 2.0  # saved just now


def test_age_none_when_missing(cp_path: Path):
    cp = Checkpoint(cp_path)
    assert cp.age() is None


# ---- exists / remove ----


def test_exists_lifecycle(cp_path: Path):
    cp = Checkpoint(cp_path)
    assert not cp.exists()
    cp.save({"a": 1})
    assert cp.exists()
    cp.remove()
    assert not cp.exists()


def test_remove_idempotent(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.remove()  # should not raise
    cp.remove()


# ---- atomicity ----


def test_no_temp_file_left_after_save(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({"stroke": 7})
    tmps = list(cp_path.parent.glob("*.tmp"))
    assert tmps == [], "no leftover temp files"


def test_creates_parent_dirs(tmp_path: Path):
    deep = tmp_path / "a" / "b" / "c" / "cp.json"
    cp = Checkpoint(deep)
    cp.save({"nested": True})
    assert cp.load() == {"nested": True}


# ---- edge cases ----


def test_empty_dict(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({})
    assert cp.load() == {}


def test_large_payload(cp_path: Path):
    cp = Checkpoint(cp_path)
    big = {f"key_{i}": f"value_{i}" * 100 for i in range(500)}
    cp.save(big)
    loaded = cp.load()
    assert loaded == big


def test_numeric_types_preserved(cp_path: Path):
    cp = Checkpoint(cp_path)
    cp.save({"int": 42, "float": 3.14, "neg": -7, "zero": 0})
    loaded = cp.load()
    assert loaded["int"] == 42
    assert loaded["float"] == pytest.approx(3.14)
    assert loaded["neg"] == -7
