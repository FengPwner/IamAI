"""Tests for iamai.stroke_anchor — push checkpoint for batch committer."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from iamai.stroke_anchor import (
    save_anchor,
    load_anchor,
    verify_anchor,
    pending_since,
    reset_anchor,
    _stroke_hash,
    _anchor_path,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal repo layout with data/ directory."""
    (tmp_path / "data").mkdir()
    return tmp_path


def _write_strokes(repo: Path, lines: list[str]) -> None:
    """Write JSONL lines to data/strokes.jsonl."""
    (repo / "data" / "strokes.jsonl").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# _stroke_hash
# ---------------------------------------------------------------------------


class TestStrokeHash:
    def test_deterministic(self):
        assert _stroke_hash("hello") == _stroke_hash("hello")

    def test_different_inputs(self):
        assert _stroke_hash("hello") != _stroke_hash("world")

    def test_length(self):
        h = _stroke_hash("test line")
        assert len(h) == 8

    def test_hex_chars(self):
        h = _stroke_hash("some stroke content")
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_string(self):
        h = _stroke_hash("")
        assert len(h) == 8


# ---------------------------------------------------------------------------
# _anchor_path
# ---------------------------------------------------------------------------


class TestAnchorPath:
    def test_default_writer(self, tmp_path: Path):
        p = _anchor_path(tmp_path)
        assert p == tmp_path / "data" / "stroke_anchor.qwen.json"

    def test_custom_writer(self, tmp_path: Path):
        p = _anchor_path(tmp_path, writer="doubao")
        assert p == tmp_path / "data" / "stroke_anchor.doubao.json"


# ---------------------------------------------------------------------------
# save_anchor / load_anchor
# ---------------------------------------------------------------------------


class TestSaveLoadAnchor:
    def test_round_trip(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        stroke_line = '{"seq": 42, "kind": "note", "text": "hello"}'

        anchor = save_anchor(repo, offset=100, last_seq=42,
                             stroke_line=stroke_line)
        assert anchor["offset"] == 100
        assert anchor["last_seq"] == 42
        assert anchor["stroke_hash"] == _stroke_hash(stroke_line)
        assert "pushed_at" in anchor

        loaded = load_anchor(repo)
        assert loaded is not None
        assert loaded["offset"] == 100
        assert loaded["last_seq"] == 42
        assert loaded["stroke_hash"] == _stroke_hash(stroke_line)

    def test_load_missing(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert load_anchor(repo) is None

    def test_load_corrupt(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        (repo / "data" / "stroke_anchor.qwen.json").write_text("not json{{{")
        assert load_anchor(repo) is None

    def test_load_missing_fields(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        (repo / "data" / "stroke_anchor.qwen.json").write_text(
            json.dumps({"offset": 0})  # missing last_seq, stroke_hash, pushed_at
        )
        assert load_anchor(repo) is None

    def test_custom_writer(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        save_anchor(repo, writer="doubao", offset=50, last_seq=10,
                    stroke_line="line")
        assert load_anchor(repo, writer="qwen") is None
        loaded = load_anchor(repo, writer="doubao")
        assert loaded is not None
        assert loaded["offset"] == 50

    def test_overwrite_anchor(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        save_anchor(repo, offset=10, last_seq=1, stroke_line="a")
        save_anchor(repo, offset=20, last_seq=2, stroke_line="b")
        loaded = load_anchor(repo)
        assert loaded["offset"] == 20
        assert loaded["last_seq"] == 2

    def test_empty_stroke_line(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        anchor = save_anchor(repo, offset=0, last_seq=0, stroke_line="")
        assert anchor["stroke_hash"] == ""

    def test_creates_data_dir(self, tmp_path: Path):
        repo = tmp_path / "new_repo"
        repo.mkdir()
        save_anchor(repo, offset=5, last_seq=1, stroke_line="x")
        assert (repo / "data" / "stroke_anchor.qwen.json").exists()


# ---------------------------------------------------------------------------
# verify_anchor
# ---------------------------------------------------------------------------


class TestVerifyAnchor:
    def test_valid_anchor(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        lines = [
            '{"seq": 1, "kind": "note", "text": "first"}',
            '{"seq": 2, "kind": "note", "text": "second"}',
        ]
        _write_strokes(repo, lines)
        # offset = length of first line + newline
        offset = len(lines[0].encode()) + 1
        save_anchor(repo, offset=offset, last_seq=1, stroke_line=lines[0])
        assert verify_anchor(repo) is True

    def test_hash_mismatch(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        lines = ['{"seq": 1, "kind": "note", "text": "first"}']
        _write_strokes(repo, lines)
        offset = len(lines[0].encode()) + 1
        save_anchor(repo, offset=offset, last_seq=1,
                    stroke_line="different content")
        assert verify_anchor(repo) is False

    def test_missing_anchor(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        _write_strokes(repo, ['{"seq": 1}'])
        assert verify_anchor(repo) is False

    def test_missing_strokes_file(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        save_anchor(repo, offset=0, last_seq=0, stroke_line="x")
        assert verify_anchor(repo) is False

    def test_zero_offset(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        save_anchor(repo, offset=0, last_seq=0, stroke_line="x")
        _write_strokes(repo, ['{"seq": 1}'])
        # offset=0 means prefix is empty → no lines → False
        assert verify_anchor(repo) is False


# ---------------------------------------------------------------------------
# pending_since
# ---------------------------------------------------------------------------


class TestPendingSince:
    def test_no_anchor(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        _write_strokes(repo, ['{"seq": 1}'])
        assert pending_since(repo) == 0

    def test_no_new_strokes(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        line = '{"seq": 1, "kind": "note", "text": "hello"}'
        _write_strokes(repo, [line])
        # Anchor at end of file.
        size = (repo / "data" / "strokes.jsonl").stat().st_size
        save_anchor(repo, offset=size, last_seq=1, stroke_line=line)
        assert pending_since(repo) == 0

    def test_new_strokes_after_anchor(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        line1 = '{"seq": 1, "kind": "note", "text": "first"}'
        _write_strokes(repo, [line1])
        size_after_first = (repo / "data" / "strokes.jsonl").stat().st_size
        save_anchor(repo, offset=size_after_first, last_seq=1,
                    stroke_line=line1)

        # Append more strokes.
        with open(repo / "data" / "strokes.jsonl", "a") as f:
            f.write('{"seq": 2, "kind": "note", "text": "second"}\n')
            f.write('{"seq": 3, "kind": "note", "text": "third"}\n')

        assert pending_since(repo) == 2

    def test_missing_strokes_file(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        save_anchor(repo, offset=0, last_seq=0, stroke_line="")
        assert pending_since(repo) == 0

    def test_file_shrunk(self, tmp_path: Path):
        """If the file was truncated past the anchor, return 0."""
        repo = _make_repo(tmp_path)
        line = '{"seq": 1, "kind": "note", "text": "data"}'
        _write_strokes(repo, [line])
        save_anchor(repo, offset=999999, last_seq=1, stroke_line=line)
        assert pending_since(repo) == 0


# ---------------------------------------------------------------------------
# reset_anchor
# ---------------------------------------------------------------------------


class TestResetAnchor:
    def test_reset_existing(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        save_anchor(repo, offset=10, last_seq=1, stroke_line="x")
        assert (repo / "data" / "stroke_anchor.qwen.json").exists()
        assert reset_anchor(repo) is True
        assert not (repo / "data" / "stroke_anchor.qwen.json").exists()
        assert load_anchor(repo) is None

    def test_reset_missing(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert reset_anchor(repo) is False

    def test_reset_custom_writer(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        save_anchor(repo, writer="doubao", offset=5, last_seq=1,
                    stroke_line="y")
        assert reset_anchor(repo, writer="qwen") is False
        assert reset_anchor(repo, writer="doubao") is True


# ---------------------------------------------------------------------------
# integration: save → verify → pending → reset cycle
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_cycle(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        strokes = [
            '{"seq": 1, "kind": "note", "text": "alpha"}',
            '{"seq": 2, "kind": "note", "text": "beta"}',
        ]
        _write_strokes(repo, strokes)

        # Anchor after first stroke.
        offset = len(strokes[0].encode()) + 1
        save_anchor(repo, offset=offset, last_seq=1, stroke_line=strokes[0])

        # Verify passes.
        assert verify_anchor(repo) is True

        # One stroke pending (seq 2).
        assert pending_since(repo) == 1

        # Append two more.
        with open(repo / "data" / "strokes.jsonl", "a") as f:
            f.write('{"seq": 3, "kind": "note", "text": "gamma"}\n')
            f.write('{"seq": 4, "kind": "note", "text": "delta"}\n')
        assert pending_since(repo) == 3

        # Reset and re-anchor after all strokes.
        assert reset_anchor(repo) is True
        full_size = (repo / "data" / "strokes.jsonl").stat().st_size
        save_anchor(repo, offset=full_size, last_seq=4,
                    stroke_line='{"seq": 4, "kind": "note", "text": "delta"}')
        assert pending_since(repo) == 0
        assert verify_anchor(repo) is True
