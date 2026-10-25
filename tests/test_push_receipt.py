"""Tests for iamai.push_receipt — tamper-evident push verification."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from iamai.push_receipt import (
    record_receipt,
    latest_receipt,
    verify_receipt,
    push_history,
    verify_chain,
    receipt_digest,
    total_pushes,
    total_commits_pushed,
    reset_receipts,
    _receipts_path,
    _next_seq,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal repo layout with data/ directory."""
    (tmp_path / "data").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# receipt_digest
# ---------------------------------------------------------------------------


class TestReceiptDigest:
    def test_deterministic(self):
        assert receipt_digest(["abc", "def"]) == receipt_digest(["abc", "def"])

    def test_order_independent(self):
        """Sorted internally, so different input orders produce same digest."""
        assert receipt_digest(["def", "abc"]) == receipt_digest(["abc", "def"])

    def test_different_commits(self):
        assert receipt_digest(["abc"]) != receipt_digest(["xyz"])

    def test_length(self):
        d = receipt_digest(["a1b2c3"])
        assert len(d) == 64  # SHA-256 hex

    def test_hex_chars(self):
        d = receipt_digest(["commit1", "commit2"])
        assert all(c in "0123456789abcdef" for c in d)

    def test_empty_list(self):
        d = receipt_digest([])
        assert len(d) == 64

    def test_single_commit(self):
        d = receipt_digest(["abc1234"])
        assert len(d) == 64


# ---------------------------------------------------------------------------
# _receipts_path
# ---------------------------------------------------------------------------


class TestReceiptsPath:
    def test_default_writer(self, tmp_path: Path):
        p = _receipts_path(tmp_path)
        assert p == tmp_path / "data" / "push_receipts.qwen.jsonl"

    def test_custom_writer(self, tmp_path: Path):
        p = _receipts_path(tmp_path, writer="doubao")
        assert p == tmp_path / "data" / "push_receipts.doubao.jsonl"


# ---------------------------------------------------------------------------
# _next_seq
# ---------------------------------------------------------------------------


class TestNextSeq:
    def test_empty(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert _next_seq(repo) == 1

    def test_after_one_receipt(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a1b2c3"])
        assert _next_seq(repo) == 2

    def test_after_multiple(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        record_receipt(repo, commits=["b"])
        record_receipt(repo, commits=["c"])
        assert _next_seq(repo) == 4

    def test_corrupt_file(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        path = _receipts_path(repo)
        path.write_text("not json\n")
        assert _next_seq(repo) == 1


# ---------------------------------------------------------------------------
# record_receipt / latest_receipt
# ---------------------------------------------------------------------------


class TestRecordAndLatest:
    def test_basic_record(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        r = record_receipt(repo, commits=["abc1234", "def5678"])
        assert r["commits"] == ["abc1234", "def5678"]
        assert r["remote"] == "origin"
        assert r["branch"] == "main"
        assert r["seq"] == 1
        assert len(r["digest"]) == 64

    def test_custom_params(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        r = record_receipt(
            repo,
            writer="doubao",
            commits=["aaa"],
            remote="upstream",
            branch="dev",
            pushed_at="2026-10-17T12:00:00+08:00",
        )
        assert r["remote"] == "upstream"
        assert r["branch"] == "dev"
        assert r["pushed_at"] == "2026-10-17T12:00:00+08:00"

    def test_latest_receipt(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["first"])
        record_receipt(repo, commits=["second"])
        record_receipt(repo, commits=["third"])
        latest = latest_receipt(repo)
        assert latest["commits"] == ["third"]
        assert latest["seq"] == 3

    def test_latest_none_when_empty(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert latest_receipt(repo) is None

    def test_latest_none_no_file(self, tmp_path: Path):
        assert latest_receipt(tmp_path) is None

    def test_seq_increments(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        r1 = record_receipt(repo, commits=["a"])
        r2 = record_receipt(repo, commits=["b"])
        assert r2["seq"] == r1["seq"] + 1

    def test_empty_commits(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        r = record_receipt(repo)
        assert r["commits"] == []
        assert len(r["digest"]) == 64

    def test_creates_data_dir(self, tmp_path: Path):
        repo = tmp_path / "new_repo"
        repo.mkdir()
        record_receipt(repo, commits=["x"])
        assert (repo / "data").exists()

    def test_file_is_jsonl(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        record_receipt(repo, commits=["b"])
        lines = _receipts_path(repo).read_text().strip().split("\n")
        assert len(lines) == 2
        # Each line is valid JSON.
        for line in lines:
            json.loads(line)

    def test_overwrite_none(self, tmp_path: Path):
        """Multiple receipts don't overwrite — they append."""
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["first"])
        record_receipt(repo, commits=["second"])
        history = push_history(repo)
        assert len(history) == 2

    def test_writer_isolation(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, writer="qwen", commits=["q1"])
        record_receipt(repo, writer="doubao", commits=["d1"])
        assert latest_receipt(repo, "qwen")["commits"] == ["q1"]
        assert latest_receipt(repo, "doubao")["commits"] == ["d1"]


# ---------------------------------------------------------------------------
# verify_receipt
# ---------------------------------------------------------------------------


class TestVerifyReceipt:
    def test_valid(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["abc", "def"])
        ok, reason = verify_receipt(repo)
        assert ok is True
        assert reason == "ok"

    def test_no_file(self, tmp_path: Path):
        ok, reason = verify_receipt(tmp_path)
        assert ok is False
        assert "no receipts" in reason

    def test_tampered_digest(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["abc"])
        # Tamper: rewrite the file with wrong digest.
        path = _receipts_path(repo)
        lines = path.read_text().strip().split("\n")
        entry = json.loads(lines[-1])
        entry["digest"] = "0" * 64
        path.write_text(json.dumps(entry) + "\n")
        ok, reason = verify_receipt(repo)
        assert ok is False
        assert "digest mismatch" in reason

    def test_missing_field(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["abc"])
        path = _receipts_path(repo)
        entry = json.loads(path.read_text().strip())
        del entry["digest"]
        path.write_text(json.dumps(entry) + "\n")
        ok, reason = verify_receipt(repo)
        assert ok is False
        assert "missing field" in reason

    def test_verify_by_seq(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["first"])
        record_receipt(repo, commits=["second"])
        ok, reason = verify_receipt(repo, seq=1)
        assert ok is True
        ok, reason = verify_receipt(repo, seq=2)
        assert ok is True

    def test_verify_nonexistent_seq(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["abc"])
        ok, reason = verify_receipt(repo, seq=99)
        assert ok is False
        assert "not found" in reason

    def test_corrupt_json(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        path = _receipts_path(repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json\n")
        ok, reason = verify_receipt(repo)
        assert ok is False
        assert "no valid receipts" in reason


# ---------------------------------------------------------------------------
# push_history
# ---------------------------------------------------------------------------


class TestPushHistory:
    def test_empty(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert push_history(repo) == []

    def test_no_file(self, tmp_path: Path):
        assert push_history(tmp_path) == []

    def test_multiple(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        record_receipt(repo, commits=["b"])
        record_receipt(repo, commits=["c"])
        h = push_history(repo)
        assert len(h) == 3
        assert h[0]["seq"] == 1
        assert h[2]["seq"] == 3

    def test_skips_blank_lines(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        # Append a blank line.
        path = _receipts_path(repo)
        with open(path, "a") as f:
            f.write("\n")
        record_receipt(repo, commits=["b"])
        h = push_history(repo)
        assert len(h) == 2

    def test_skips_corrupt_lines(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        path = _receipts_path(repo)
        with open(path, "a") as f:
            f.write("bad json\n")
        record_receipt(repo, commits=["b"])
        h = push_history(repo)
        assert len(h) == 2  # corrupt line skipped


# ---------------------------------------------------------------------------
# verify_chain
# ---------------------------------------------------------------------------


class TestVerifyChain:
    def test_valid_chain(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        record_receipt(repo, commits=["b"])
        record_receipt(repo, commits=["c"])
        ok, reason = verify_chain(repo)
        assert ok is True

    def test_empty(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        ok, reason = verify_chain(repo)
        assert ok is False

    def test_gap_detected(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])  # seq 1
        # Manually write seq 3 (skip 2).
        path = _receipts_path(repo)
        entry = {
            "commits": ["c"],
            "remote": "origin",
            "branch": "main",
            "digest": receipt_digest(["c"]),
            "pushed_at": "2026-10-17T11:00:00+08:00",
            "seq": 3,
        }
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        ok, reason = verify_chain(repo)
        assert ok is False
        assert "seq gap" in reason

    def test_non_monotonic_seq(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])  # seq 1
        record_receipt(repo, commits=["b"])  # seq 2
        # Manually write seq 1 again.
        path = _receipts_path(repo)
        entry = {
            "commits": ["c"],
            "remote": "origin",
            "branch": "main",
            "digest": receipt_digest(["c"]),
            "pushed_at": "2026-10-17T11:00:00+08:00",
            "seq": 1,
        }
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        ok, reason = verify_chain(repo)
        assert ok is False
        assert "seq 1 <=" in reason

    def test_digest_mismatch_in_chain(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        record_receipt(repo, commits=["b"])
        # Tamper with second receipt.
        path = _receipts_path(repo)
        lines = path.read_text().strip().split("\n")
        entry = json.loads(lines[1])
        entry["digest"] = "0" * 64
        path.write_text(lines[0] + "\n" + json.dumps(entry) + "\n")
        ok, reason = verify_chain(repo)
        assert ok is False
        assert "digest mismatch" in reason

    def test_single_receipt_chain(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["only"])
        ok, reason = verify_chain(repo)
        assert ok is True


# ---------------------------------------------------------------------------
# total_pushes / total_commits_pushed
# ---------------------------------------------------------------------------


class TestTotals:
    def test_total_pushes_empty(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert total_pushes(repo) == 0

    def test_total_pushes(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        record_receipt(repo, commits=["b", "c"])
        assert total_pushes(repo) == 2

    def test_total_commits_pushed(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        record_receipt(repo, commits=["b", "c", "d"])
        record_receipt(repo, commits=["e"])
        assert total_commits_pushed(repo) == 5

    def test_total_commits_empty_pushes(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo)
        record_receipt(repo)
        assert total_commits_pushed(repo) == 0


# ---------------------------------------------------------------------------
# reset_receipts
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_exists(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, commits=["a"])
        assert reset_receipts(repo) is True
        assert push_history(repo) == []

    def test_reset_not_exists(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert reset_receipts(repo) is False

    def test_reset_custom_writer(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, writer="doubao", commits=["x"])
        assert reset_receipts(repo, writer="doubao") is True
        assert latest_receipt(repo, "doubao") is None

    def test_reset_isolation(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        record_receipt(repo, writer="qwen", commits=["q"])
        record_receipt(repo, writer="doubao", commits=["d"])
        reset_receipts(repo, writer="qwen")
        assert latest_receipt(repo, "qwen") is None
        assert latest_receipt(repo, "doubao")["commits"] == ["d"]


# ---------------------------------------------------------------------------
# integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_lifecycle(self, tmp_path: Path):
        """Record → verify → history → chain → reset → re-record."""
        repo = _make_repo(tmp_path)

        # Phase 1: record three pushes.
        record_receipt(repo, commits=["aaa1111", "bbb2222"])
        record_receipt(repo, commits=["ccc3333"])
        record_receipt(repo, commits=["ddd4444", "eee5555", "fff6666"])

        # Verify latest.
        ok, reason = verify_receipt(repo)
        assert ok is True

        # Verify chain.
        ok, reason = verify_chain(repo)
        assert ok is True

        # History.
        h = push_history(repo)
        assert len(h) == 3
        assert total_pushes(repo) == 3
        assert total_commits_pushed(repo) == 6

        # Verify by seq.
        ok, _ = verify_receipt(repo, seq=2)
        assert ok is True

        # Phase 2: reset and re-record.
        assert reset_receipts(repo) is True
        assert push_history(repo) == []
        assert total_pushes(repo) == 0

        r = record_receipt(repo, commits=["new1111"])
        assert r["seq"] == 1  # seq restarts after reset
        ok, reason = verify_chain(repo)
        assert ok is True

    def test_multi_writer(self, tmp_path: Path):
        """Two independent writers sharing the same data/ dir."""
        repo = _make_repo(tmp_path)

        record_receipt(repo, writer="qwen", commits=["q1"])
        record_receipt(repo, writer="doubao", commits=["d1", "d2"])
        record_receipt(repo, writer="qwen", commits=["q2"])

        assert total_pushes(repo, "qwen") == 2
        assert total_pushes(repo, "doubao") == 1
        assert total_commits_pushed(repo, "qwen") == 2
        assert total_commits_pushed(repo, "doubao") == 2

        ok, _ = verify_chain(repo, "qwen")
        assert ok is True
        ok, _ = verify_chain(repo, "doubao")
        assert ok is True
