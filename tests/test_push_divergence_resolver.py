"""Tests for iamai.push_divergence_resolver.

Covers the five divergence types and the outcome tracking API.
Written during caretaker visit 452 (2026-11-01) to address the
recurring push-divergence pattern seen in visits 441-452.
"""

import pytest

from iamai.push_divergence_resolver import (
    DivergenceReport,
    OutcomeRecord,
    classify_divergence,
    clear_outcomes,
    outcome_summary,
    record_outcome,
    strategy_success_rate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_outcomes():
    """Reset outcome log before each test."""
    clear_outcomes()
    yield
    clear_outcomes()


# ---------------------------------------------------------------------------
# Trivial cases
# ---------------------------------------------------------------------------

class TestTrivialCases:

    def test_clean_ahead(self):
        """Local has commits, remote has none — just push."""
        report = classify_divergence(local_commits=3, remote_commits=0)
        assert report.divergence_type == "clean_ahead"
        assert report.strategy == "push"
        assert report.local_commits == 3

    def test_fast_forward(self):
        """Remote has commits, local has none — pull fast-forward."""
        report = classify_divergence(local_commits=0, remote_commits=2)
        assert report.divergence_type == "fast_forward"
        assert report.strategy == "pull_ff"
        assert report.remote_commits == 2

    def test_both_zero(self):
        """Branches in sync — nothing to do."""
        report = classify_divergence(local_commits=0, remote_commits=0)
        assert report.divergence_type == "clean_ahead"
        assert report.strategy == "push"


# ---------------------------------------------------------------------------
# Diverged cases
# ---------------------------------------------------------------------------

class TestDivergedCases:

    def test_diverged_trivial_no_overlap(self):
        """Both sides have commits, but touching different files."""
        report = classify_divergence(
            local_commits=2,
            remote_commits=1,
            local_files=["docs/DEVLOG.md", "data/strokes.jsonl"],
            remote_files=["guoban/guoban-note.md"],
        )
        assert report.divergence_type == "diverged_trivial"
        assert report.strategy == "rebase"
        assert report.overlapping_files == []

    def test_diverged_state_files_only(self):
        """Conflicts only in state files — rebase with -X theirs."""
        report = classify_divergence(
            local_commits=3,
            remote_commits=1,
            local_files=["data/strokes.jsonl", "data/writer_state.qwen.json", "docs/DEVLOG.md"],
            remote_files=["data/strokes.jsonl", "data/writer_state.qwen.json"],
        )
        assert report.divergence_type == "diverged_state"
        assert report.strategy == "rebase_theirs"
        assert "data/strokes.jsonl" in report.state_file_conflicts
        assert "data/writer_state.qwen.json" in report.state_file_conflicts
        assert report.confidence == "high"

    def test_diverged_conflict_non_state(self):
        """Conflicts in non-state files — reset and re-apply."""
        report = classify_divergence(
            local_commits=2,
            remote_commits=2,
            local_files=["notes/reading.md", "docs/DEVLOG.md"],
            remote_files=["notes/reading.md", "guoban/guoban-note.md"],
        )
        assert report.divergence_type == "diverged_conflict"
        assert report.strategy == "reset_apply"
        assert "notes/reading.md" in report.overlapping_files
        assert report.confidence == "medium"

    def test_diverged_mixed_conflict(self):
        """Conflicts in both state and non-state files — reset_apply wins."""
        report = classify_divergence(
            local_commits=3,
            remote_commits=1,
            local_files=["data/strokes.jsonl", "notes/history.md"],
            remote_files=["data/strokes.jsonl", "notes/history.md"],
        )
        assert report.divergence_type == "diverged_conflict"
        assert report.strategy == "reset_apply"
        assert "notes/history.md" in report.overlapping_files
        assert "data/strokes.jsonl" in report.state_file_conflicts

    def test_empty_file_lists_treated_as_no_overlap(self):
        """If file lists are empty despite divergence, classify as trivial."""
        report = classify_divergence(
            local_commits=1,
            remote_commits=1,
            local_files=[],
            remote_files=[],
        )
        assert report.divergence_type == "diverged_trivial"
        assert report.strategy == "rebase"


# ---------------------------------------------------------------------------
# State file detection
# ---------------------------------------------------------------------------

class TestStateFileDetection:

    def test_jsonl_under_data(self):
        report = classify_divergence(
            local_commits=1, remote_commits=1,
            local_files=["data/custom.jsonl"],
            remote_files=["data/custom.jsonl"],
        )
        assert report.divergence_type == "diverged_state"

    def test_json_under_data(self):
        report = classify_divergence(
            local_commits=1, remote_commits=1,
            local_files=["data/metrics.json"],
            remote_files=["data/metrics.json"],
        )
        assert report.divergence_type == "diverged_state"

    def test_non_state_json_outside_data(self):
        report = classify_divergence(
            local_commits=1, remote_commits=1,
            local_files=["config/settings.json"],
            remote_files=["config/settings.json"],
        )
        assert report.divergence_type == "diverged_conflict"

    def test_extra_state_patterns(self):
        report = classify_divergence(
            local_commits=1, remote_commits=1,
            local_files=["custom/state.bin"],
            remote_files=["custom/state.bin"],
            state_files=["custom/state.bin"],
        )
        assert report.divergence_type == "diverged_state"


# ---------------------------------------------------------------------------
# Outcome tracking
# ---------------------------------------------------------------------------

class TestOutcomeTracking:

    def test_record_success(self):
        report = classify_divergence(local_commits=1, remote_commits=0)
        record = record_outcome(report, success=True)
        assert isinstance(record, OutcomeRecord)
        assert record.success is True
        assert record.divergence_type == "clean_ahead"

    def test_record_failure_with_conflicts(self):
        report = classify_divergence(
            local_commits=2, remote_commits=1,
            local_files=["notes/x.md"], remote_files=["notes/x.md"],
        )
        record = record_outcome(report, success=False, conflict_count=3, notes="rebase failed")
        assert record.success is False
        assert record.conflict_count == 3
        assert record.notes == "rebase failed"

    def test_strategy_success_rate(self):
        report_push = classify_divergence(local_commits=1, remote_commits=0)
        report_rebase = classify_divergence(
            local_commits=1, remote_commits=1,
            local_files=["a.py"], remote_files=["b.py"],
        )

        record_outcome(report_push, success=True)
        record_outcome(report_push, success=True)
        record_outcome(report_rebase, success=True)
        record_outcome(report_rebase, success=False)

        assert strategy_success_rate("push") == 1.0
        assert strategy_success_rate("rebase") == 0.5
        assert strategy_success_rate("nonexistent") is None

    def test_outcome_summary(self):
        report = classify_divergence(local_commits=1, remote_commits=0)
        record_outcome(report, success=True)
        record_outcome(report, success=True)
        record_outcome(report, success=False)

        summary = outcome_summary()
        assert summary["push"]["success"] == 2
        assert summary["push"]["failure"] == 1

    def test_clear_outcomes(self):
        report = classify_divergence(local_commits=1, remote_commits=0)
        record_outcome(report, success=True)
        clear_outcomes()
        assert strategy_success_rate("push") is None
        assert outcome_summary() == {}


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:

    def test_report_is_frozen(self):
        report = classify_divergence(local_commits=1, remote_commits=0)
        with pytest.raises(AttributeError):
            report.strategy = "something_else"

    def test_summary_is_nonempty(self):
        for lc, rc in [(1, 0), (0, 1), (1, 1), (0, 0)]:
            report = classify_divergence(local_commits=lc, remote_commits=rc)
            assert report.summary, f"empty summary for ({lc}, {rc})"

    def test_default_lists_are_independent(self):
        """Ensure default mutable lists don't leak between calls."""
        r1 = classify_divergence(local_commits=1, remote_commits=0)
        r2 = classify_divergence(local_commits=1, remote_commits=0)
        assert r1.overlapping_files == []
        assert r2.overlapping_files == []
        assert r1.overlapping_files is not r2.overlapping_files
