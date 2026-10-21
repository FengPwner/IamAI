"""Tests for iamai.stroke_type_balance."""

import json
import math
import tempfile
from pathlib import Path

import pytest

from iamai.stroke_type_balance import (
    EXPECTED_KINDS,
    N_KINDS,
    BalanceReport,
    balance_from_kinds,
    balance_report,
    balance_summary,
    compute_evenness,
    compute_shares,
    find_dominant,
    find_missing,
    verdict_for,
)


# ---------------------------------------------------------------------------
# compute_shares
# ---------------------------------------------------------------------------

class TestComputeShares:
    def test_uniform(self):
        counts = {k: 10 for k in EXPECTED_KINDS}
        shares = compute_shares(counts, 60)
        for v in shares.values():
            assert abs(v - 1 / N_KINDS) < 1e-9

    def test_zero_total(self):
        shares = compute_shares({}, 0)
        assert all(v == 0.0 for v in shares.values())

    def test_single_kind(self):
        counts = {"devlog": 50}
        shares = compute_shares(counts, 50)
        assert shares["devlog"] == 1.0
        assert shares["metrics"] == 0.0

    def test_missing_kinds_get_zero(self):
        counts = {"metrics": 30, "note": 30}
        shares = compute_shares(counts, 60)
        assert shares["metrics"] == 0.5
        assert shares["garden"] == 0.0

    def test_sums_to_one(self):
        counts = {"metrics": 10, "note": 20, "snippet": 5,
                  "thought": 15, "devlog": 8, "garden": 12}
        shares = compute_shares(counts, sum(counts.values()))
        assert abs(sum(shares.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# compute_evenness
# ---------------------------------------------------------------------------

class TestComputeEvenness:
    def test_perfectly_uniform(self):
        shares = {k: 1 / N_KINDS for k in EXPECTED_KINDS}
        e = compute_evenness(shares)
        assert abs(e - 1.0) < 1e-9

    def test_all_one_kind(self):
        shares = {k: 0.0 for k in EXPECTED_KINDS}
        shares["devlog"] = 1.0
        e = compute_evenness(shares)
        assert e == 0.0

    def test_empty(self):
        assert compute_evenness({}) == 0.0

    def test_two_kinds_equally(self):
        shares = {k: 0.0 for k in EXPECTED_KINDS}
        shares["metrics"] = 0.5
        shares["note"] = 0.5
        e = compute_evenness(shares)
        # entropy = ln(2), max = ln(6) → e = ln(2)/ln(6) ≈ 0.387
        expected = math.log(2) / math.log(6)
        assert abs(e - expected) < 1e-6

    def test_between_zero_and_one(self):
        shares = {"metrics": 0.4, "note": 0.3, "snippet": 0.2,
                  "thought": 0.05, "devlog": 0.03, "garden": 0.02}
        e = compute_evenness(shares)
        assert 0.0 < e < 1.0


# ---------------------------------------------------------------------------
# verdict_for
# ---------------------------------------------------------------------------

class TestVerdictFor:
    def test_balanced(self):
        assert verdict_for(0.90) == "balanced"
        assert verdict_for(0.85) == "balanced"

    def test_skewed(self):
        assert verdict_for(0.70) == "skewed"
        assert verdict_for(0.60) == "skewed"

    def test_lopsided(self):
        assert verdict_for(0.50) == "lopsided"
        assert verdict_for(0.0) == "lopsided"


# ---------------------------------------------------------------------------
# find_dominant / find_missing
# ---------------------------------------------------------------------------

class TestFindDominant:
    def test_basic(self):
        assert find_dominant({"devlog": 40, "metrics": 10}) == "devlog"

    def test_empty(self):
        assert find_dominant({}) is None

    def test_zero_counts(self):
        assert find_dominant({"a": 0, "b": 0}) is None

    def test_tie_returns_one(self):
        counts = {"metrics": 10, "note": 10}
        assert find_dominant(counts) in ("metrics", "note")


class TestFindMissing:
    def test_all_present(self):
        counts = {k: 1 for k in EXPECTED_KINDS}
        assert find_missing(counts) == []

    def test_some_missing(self):
        counts = {"metrics": 5, "note": 3}
        missing = find_missing(counts)
        assert set(missing) == set(EXPECTED_KINDS) - {"metrics", "note"}

    def test_empty(self):
        assert find_missing({}) == list(EXPECTED_KINDS)


# ---------------------------------------------------------------------------
# balance_from_kinds
# ---------------------------------------------------------------------------

class TestBalanceFromKinds:
    def test_perfectly_balanced(self):
        kinds = list(EXPECTED_KINDS) * 10  # 60 strokes, 10 each
        report = balance_from_kinds(kinds)
        assert report.verdict == "balanced"
        assert report.evenness == pytest.approx(1.0, abs=0.01)
        assert report.total == 60
        assert report.missing_kinds == []

    def test_single_kind_only(self):
        kinds = ["devlog"] * 60
        report = balance_from_kinds(kinds)
        assert report.verdict == "lopsided"
        assert report.evenness == 0.0
        assert report.dominant_kind == "devlog"
        assert len(report.missing_kinds) == N_KINDS - 1

    def test_two_kinds(self):
        kinds = ["metrics"] * 30 + ["note"] * 30
        report = balance_from_kinds(kinds)
        assert report.verdict == "lopsided"
        assert report.dominant_kind in ("metrics", "note")
        assert len(report.missing_kinds) == N_KINDS - 2

    def test_slightly_skewed(self):
        kinds = (["metrics"] * 15 + ["note"] * 12 + ["snippet"] * 10
                 + ["thought"] * 9 + ["devlog"] * 8 + ["garden"] * 6)
        report = balance_from_kinds(kinds)
        assert report.total == 60
        assert report.verdict in ("balanced", "skewed")

    def test_empty(self):
        report = balance_from_kinds([])
        assert report.total == 0
        assert report.verdict == "lopsided"

    def test_unknown_kinds_ignored(self):
        kinds = ["metrics"] * 10 + ["unknown_kind"] * 50
        report = balance_from_kinds(kinds)
        assert report.counts.get("unknown_kind", 0) == 50
        assert report.counts.get("metrics", 0) == 10


# ---------------------------------------------------------------------------
# balance_report (file I/O)
# ---------------------------------------------------------------------------

class TestBalanceReport:
    def _write_strokes(self, kinds: list[str], tmp: Path) -> Path:
        p = tmp / "strokes.jsonl"
        with p.open("w") as fh:
            for i, k in enumerate(kinds):
                fh.write(json.dumps({"kind": k, "seq": i, "at": "2026-10-22T00:00:00Z"}) + "\n")
        return p

    def test_reads_last_window(self, tmp_path):
        kinds = ["metrics"] * 30 + ["note"] * 30 + ["snippet"] * 30
        path = self._write_strokes(kinds, tmp_path)
        report = balance_report(path, window=30)
        # Last 30 strokes are all "snippet"
        assert report.counts.get("snippet", 0) == 30
        assert report.verdict == "lopsided"

    def test_window_larger_than_file(self, tmp_path):
        kinds = list(EXPECTED_KINDS) * 2  # 12 strokes
        path = self._write_strokes(kinds, tmp_path)
        report = balance_report(path, window=100)
        assert report.total == 12
        assert report.verdict == "balanced"

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        report = balance_report(path, window=60)
        assert report.total == 0

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("not json\n{bad\n" + json.dumps({"kind": "devlog"}) + "\n")
        report = balance_report(p, window=60)
        assert report.total == 1
        assert report.counts.get("devlog", 0) == 1


# ---------------------------------------------------------------------------
# balance_summary
# ---------------------------------------------------------------------------

class TestBalanceSummary:
    def test_empty_report(self):
        report = balance_from_kinds([])
        s = balance_summary(report)
        assert "no strokes" in s

    def test_contains_kind_lines(self):
        kinds = list(EXPECTED_KINDS) * 5
        report = balance_from_kinds(kinds)
        s = balance_summary(report)
        for k in EXPECTED_KINDS:
            assert k in s

    def test_contains_verdict(self):
        kinds = list(EXPECTED_KINDS) * 10
        report = balance_from_kinds(kinds)
        s = balance_summary(report)
        assert "balanced" in s

    def test_dominant_shown(self):
        kinds = ["devlog"] * 50 + ["metrics"] * 10
        report = balance_from_kinds(kinds)
        s = balance_summary(report)
        assert "dominant" in s
        assert "devlog" in s

    def test_missing_shown(self):
        kinds = ["metrics"] * 20
        report = balance_from_kinds(kinds)
        s = balance_summary(report)
        assert "missing" in s
