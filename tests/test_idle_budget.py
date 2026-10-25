"""Tests for idle_budget module."""

import json
import tempfile
from pathlib import Path

import pytest

from iamai.idle_budget import (
    IdleBudget,
    budget_report,
    idle_status,
    _last_stroke_timestamp,
)


class TestIdleBudgetClassify:
    """Classification of idle gaps by duration relative to cadence."""

    def test_healthy_zero(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(0) == "healthy"

    def test_healthy_within_cadence(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(10) == "healthy"
        assert b.classify(15) == "healthy"

    def test_stretching_between_cadence_and_budget(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(16) == "stretching"
        assert b.classify(100) == "stretching"
        assert b.classify(149) == "stretching"

    def test_overdue_at_budget(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(150) == "overdue"
        assert b.classify(200) == "overdue"
        assert b.classify(299) == "overdue"

    def test_critical_at_double_budget(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(300) == "critical"
        assert b.classify(600) == "critical"
        assert b.classify(3600) == "critical"

    def test_negative_idle_is_healthy(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(-1) == "healthy"
        assert b.classify(-100) == "healthy"

    def test_custom_cadence_and_tolerance(self):
        b = IdleBudget(cadence_seconds=60, tolerance=5)
        assert b.budget_seconds == 300
        assert b.classify(30) == "healthy"
        assert b.classify(61) == "stretching"
        assert b.classify(300) == "overdue"
        assert b.classify(600) == "critical"

    def test_boundary_cadence_exactly(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(15.0) == "healthy"
        assert b.classify(15.1) == "stretching"

    def test_boundary_budget_exactly(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(149.9) == "stretching"
        assert b.classify(150.0) == "overdue"

    def test_boundary_double_budget_exactly(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(299.9) == "overdue"
        assert b.classify(300.0) == "critical"

    def test_fractional_seconds(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert b.classify(0.5) == "healthy"
        assert b.classify(7.5) == "healthy"


class TestIdleBudgetProperties:
    """Budget computation and dataclass behavior."""

    def test_budget_seconds_default(self):
        b = IdleBudget()
        assert b.budget_seconds == 150  # 15 * 10

    def test_budget_seconds_custom(self):
        b = IdleBudget(cadence_seconds=30, tolerance=20)
        assert b.budget_seconds == 600

    def test_frozen_dataclass(self):
        b = IdleBudget()
        with pytest.raises(AttributeError):
            b.cadence_seconds = 99

    def test_repr(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        assert "IdleBudget" in repr(b)
        assert "15" in repr(b)


class TestDescribe:
    """Human-readable status descriptions."""

    def test_healthy_description(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        desc = b.describe(5)
        assert "healthy" in desc
        assert "5s idle" in desc
        assert "150s" in desc

    def test_overdue_description(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        desc = b.describe(200)
        assert "overdue" in desc
        assert "200s idle" in desc

    def test_critical_description(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        desc = b.describe(500)
        assert "critical" in desc
        assert "500s idle" in desc

    def test_stretching_description(self):
        b = IdleBudget(cadence_seconds=15, tolerance=10)
        desc = b.describe(100)
        assert "stretching" in desc
        assert "100s idle" in desc


class TestLastStrokeTimestamp:
    """Reading timestamps from strokes.jsonl."""

    def test_missing_file(self):
        result = _last_stroke_timestamp(Path("/nonexistent/strokes.jsonl"))
        assert result is None

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            f.flush()
            result = _last_stroke_timestamp(Path(f.name))
            assert result is None

    def test_valid_json_with_timestamp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"timestamp": 1697000000, "kind": "note"}) + "\n")
            f.write(json.dumps({"timestamp": 1697000100, "kind": "thought"}) + "\n")
            f.flush()
            result = _last_stroke_timestamp(Path(f.name))
            assert result == 1697000100.0

    def test_valid_json_with_iso_timestamp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"timestamp": "2026-10-18T00:00:00Z"}) + "\n")
            f.flush()
            result = _last_stroke_timestamp(Path(f.name))
            assert result is not None
            assert isinstance(result, float)

    def test_json_with_ts_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"ts": 1697000200}) + "\n")
            f.flush()
            result = _last_stroke_timestamp(Path(f.name))
            assert result == 1697000200.0

    def test_json_with_at_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"at": 1697000300}) + "\n")
            f.flush()
            result = _last_stroke_timestamp(Path(f.name))
            assert result == 1697000300.0

    def test_malformed_json_last_line(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"timestamp": 1697000000}) + "\n")
            f.write("not valid json\n")
            f.flush()
            result = _last_stroke_timestamp(Path(f.name))
            assert result is None

    def test_no_timestamp_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"kind": "note", "seq": 42}) + "\n")
            f.flush()
            result = _last_stroke_timestamp(Path(f.name))
            assert result is None


class TestBudgetReport:
    """Structured report generation."""

    def test_report_unknown_no_sources(self, tmp_path, monkeypatch):
        """When no strokes file or git repo exists, status is unknown."""
        import iamai.idle_budget as mod
        monkeypatch.setattr(mod, "STROKES_FILE", tmp_path / "nonexistent.jsonl")
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        report = budget_report(now=1697000000)
        assert report["status"] == "unknown"
        assert report["idle_seconds"] is None
        assert report["budget_seconds"] == 150

    def test_report_healthy_recent_stroke(self, tmp_path, monkeypatch):
        """A stroke 5 seconds ago should be healthy."""
        import iamai.idle_budget as mod
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(
            json.dumps({"timestamp": 1697000000}) + "\n"
        )
        monkeypatch.setattr(mod, "STROKES_FILE", strokes)
        report = budget_report(now=1697000005)
        assert report["status"] == "healthy"
        assert report["idle_seconds"] == 5.0
        assert report["budget_seconds"] == 150

    def test_report_overdue_stale_stroke(self, tmp_path, monkeypatch):
        """A stroke 200 seconds ago with default budget should be overdue."""
        import iamai.idle_budget as mod
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(
            json.dumps({"timestamp": 1697000000}) + "\n"
        )
        monkeypatch.setattr(mod, "STROKES_FILE", strokes)
        report = budget_report(now=1697000200)
        assert report["status"] == "overdue"
        assert report["idle_seconds"] == 200.0

    def test_report_custom_cadence(self, tmp_path, monkeypatch):
        import iamai.idle_budget as mod
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(
            json.dumps({"timestamp": 1697000000}) + "\n"
        )
        monkeypatch.setattr(mod, "STROKES_FILE", strokes)
        report = budget_report(cadence_seconds=60, tolerance=5, now=1697000100)
        assert report["budget_seconds"] == 300
        assert report["status"] == "stretching"

    def test_report_keys(self, tmp_path, monkeypatch):
        """Report always contains all expected keys."""
        import iamai.idle_budget as mod
        monkeypatch.setattr(mod, "STROKES_FILE", tmp_path / "nope.jsonl")
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        report = budget_report()
        expected_keys = {
            "status", "idle_seconds", "budget_seconds",
            "cadence_seconds", "tolerance", "last_timestamp",
        }
        assert set(report.keys()) == expected_keys


class TestIdleStatus:
    """Human-readable idle_status() function."""

    def test_unknown_when_no_sources(self, tmp_path, monkeypatch):
        import iamai.idle_budget as mod
        monkeypatch.setattr(mod, "STROKES_FILE", tmp_path / "nope.jsonl")
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        result = idle_status()
        assert "unknown" in result

    def test_healthy_with_recent_stroke(self, tmp_path, monkeypatch):
        import iamai.idle_budget as mod
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(json.dumps({"timestamp": 1697000000}) + "\n")
        monkeypatch.setattr(mod, "STROKES_FILE", strokes)
        result = idle_status(now=1697000010)
        assert "healthy" in result

    def test_overdue_with_stale_stroke(self, tmp_path, monkeypatch):
        import iamai.idle_budget as mod
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(json.dumps({"timestamp": 1697000000}) + "\n")
        monkeypatch.setattr(mod, "STROKES_FILE", strokes)
        result = idle_status(now=1697000200)
        assert "overdue" in result
