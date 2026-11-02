"""Tests for tools/pipeline_timeline.py — pipeline temporal health monitor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

from pipeline_timeline import (  # noqa: E402
    TimelinePoint,
    Gap,
    find_repo_root,
    last_stroke_time,
    last_commit_time,
    last_push_time,
    format_age,
    classify_gap,
    build_timeline,
    STROKE_HEALTHY,
    STROKE_DEGRADED,
    COMMIT_HEALTHY,
    COMMIT_DEGRADED,
    PUSH_HEALTHY,
    PUSH_DEGRADED,
)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure for testing."""
    (tmp_path / "data").mkdir()
    (tmp_path / ".git").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_repo_with_strokes_file(self, fake_repo: Path):
        (fake_repo / "data" / "strokes.jsonl").touch()
        result = find_repo_root(fake_repo)
        assert result == fake_repo

    def test_finds_repo_from_subdirectory(self, fake_repo: Path):
        (fake_repo / "data" / "strokes.jsonl").touch()
        sub = fake_repo / "tools"
        sub.mkdir()
        result = find_repo_root(sub)
        assert result == fake_repo

    def test_returns_start_when_no_strokes(self, tmp_path: Path):
        result = find_repo_root(tmp_path)
        assert result == tmp_path


# ---------------------------------------------------------------------------
# last_stroke_time
# ---------------------------------------------------------------------------

class TestLastStrokeTime:
    def test_reads_last_line_timestamp(self, fake_repo: Path):
        strokes = fake_repo / "data" / "strokes.jsonl"
        entry = {"seq": 1, "at": "2026-11-02T08:00:00+00:00",
                 "kind": "thought", "text": "test"}
        strokes.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        result = last_stroke_time(fake_repo)
        assert result is not None
        assert abs(result - 1793606400.0) < 1

    def test_multiple_lines_reads_last(self, fake_repo: Path):
        strokes = fake_repo / "data" / "strokes.jsonl"
        e1 = json.dumps({"seq": 1, "at": "2026-11-01T00:00:00+00:00",
                         "kind": "thought", "text": "old"})
        e2 = json.dumps({"seq": 2, "at": "2026-11-02T12:00:00+00:00",
                         "kind": "thought", "text": "new"})
        strokes.write_text(e1 + "\n" + e2 + "\n", encoding="utf-8")
        result = last_stroke_time(fake_repo)
        assert result is not None
        assert abs(result - 1793620800.0) < 1

    def test_empty_file_returns_none(self, fake_repo: Path):
        (fake_repo / "data" / "strokes.jsonl").write_text("", encoding="utf-8")
        assert last_stroke_time(fake_repo) is None

    def test_missing_file_returns_none(self, fake_repo: Path):
        assert last_stroke_time(fake_repo) is None

    def test_malformed_json_returns_none(self, fake_repo: Path):
        (fake_repo / "data" / "strokes.jsonl").write_text(
            "not json\n", encoding="utf-8"
        )
        assert last_stroke_time(fake_repo) is None

    def test_missing_at_field_returns_none(self, fake_repo: Path):
        entry = json.dumps({"seq": 1, "kind": "thought", "text": "no at"})
        (fake_repo / "data" / "strokes.jsonl").write_text(
            entry + "\n", encoding="utf-8"
        )
        assert last_stroke_time(fake_repo) is None


# ---------------------------------------------------------------------------
# last_commit_time
# ---------------------------------------------------------------------------

class TestLastCommitTime:
    def test_returns_epoch_from_git(self, fake_repo: Path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1793606400\n"
        with patch("pipeline_timeline.subprocess.run", return_value=mock_result):
            result = last_commit_time(fake_repo)
        assert result == 1793606400.0

    def test_git_failure_returns_none(self, fake_repo: Path):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("pipeline_timeline.subprocess.run", return_value=mock_result):
            assert last_commit_time(fake_repo) is None

    def test_subprocess_error_returns_none(self, fake_repo: Path):
        with patch("pipeline_timeline.subprocess.run", side_effect=OSError):
            assert last_commit_time(fake_repo) is None

    def test_timeout_returns_none(self, fake_repo: Path):
        import subprocess
        with patch("pipeline_timeline.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("git", 10)):
            assert last_commit_time(fake_repo) is None


# ---------------------------------------------------------------------------
# last_push_time
# ---------------------------------------------------------------------------

class TestLastPushTime:
    def test_returns_epoch_from_remote_ref(self, fake_repo: Path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1730530000\n"
        with patch("pipeline_timeline.subprocess.run", return_value=mock_result):
            result = last_push_time(fake_repo)
        assert result == 1730530000.0

    def test_missing_remote_ref_returns_none(self, fake_repo: Path):
        mock_result = MagicMock()
        mock_result.returncode = 128
        with patch("pipeline_timeline.subprocess.run", return_value=mock_result):
            assert last_push_time(fake_repo) is None

    def test_custom_remote_and_branch(self, fake_repo: Path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1730530000\n"
        with patch("pipeline_timeline.subprocess.run",
                    return_value=mock_result) as mock_run:
            last_push_time(fake_repo, remote="upstream", branch="dev")
            call_args = mock_run.call_args[0][0]
            assert "refs/remotes/upstream/dev" in call_args


# ---------------------------------------------------------------------------
# format_age
# ---------------------------------------------------------------------------

class TestFormatAge:
    def test_none_returns_unknown(self):
        assert format_age(None) == "unknown"

    def test_seconds(self):
        assert format_age(30) == "30s"

    def test_zero(self):
        assert format_age(0) == "0s"

    def test_minutes(self):
        assert format_age(120) == "2.0m"

    def test_hours(self):
        assert format_age(7260) == "2h1m"

    def test_days(self):
        assert format_age(90000) == "1d1h"

    def test_negative_treated_as_zero(self):
        assert format_age(-5) == "0s"


# ---------------------------------------------------------------------------
# classify_gap
# ---------------------------------------------------------------------------

class TestClassifyGap:
    def test_none_is_unknown(self):
        status, detail = classify_gap(None, 60, 300)
        assert status == "unknown"

    def test_within_healthy(self):
        status, _ = classify_gap(30, 60, 300)
        assert status == "healthy"

    def test_exactly_healthy_boundary(self):
        status, _ = classify_gap(60, 60, 300)
        assert status == "healthy"

    def test_between_healthy_and_degraded(self):
        status, _ = classify_gap(120, 60, 300)
        assert status == "degraded"

    def test_exactly_degraded_boundary(self):
        status, _ = classify_gap(300, 60, 300)
        assert status == "degraded"

    def test_beyond_degraded_is_stalled(self):
        status, _ = classify_gap(500, 60, 300)
        assert status == "stalled"

    def test_negative_treated_as_zero(self):
        status, _ = classify_gap(-10, 60, 300)
        assert status == "healthy"


# ---------------------------------------------------------------------------
# TimelinePoint dataclass
# ---------------------------------------------------------------------------

class TestTimelinePoint:
    def test_with_timestamp(self):
        p = TimelinePoint("test", 1793606400.0)
        assert p.at_iso != ""
        assert "2026-11-02" in p.at_iso

    def test_without_timestamp(self):
        p = TimelinePoint("test", None)
        assert p.at_iso == ""
        assert p.age_seconds is None


# ---------------------------------------------------------------------------
# build_timeline
# ---------------------------------------------------------------------------

class TestBuildTimeline:
    def test_all_healthy(self, fake_repo: Path):
        now = 1793606500.0
        strokes = fake_repo / "data" / "strokes.jsonl"
        # Stroke 20s ago — well within STROKE_HEALTHY (60s)
        entry = json.dumps({
            "seq": 1,
            "at": "2026-11-02T08:01:20+00:00",  # 1793606480
            "kind": "thought",
            "text": "test",
        })
        strokes.write_text(entry + "\n", encoding="utf-8")

        commit_mock = MagicMock(returncode=0, stdout="1793606490\n")
        push_mock = MagicMock(returncode=0, stdout="1793606470\n")

        def side_effect(cmd, **kw):
            if "refs/remotes" in " ".join(cmd):
                return push_mock
            return commit_mock

        with patch("pipeline_timeline.subprocess.run", side_effect=side_effect):
            report = build_timeline(fake_repo, now=now)

        assert report["overall"] == "healthy"
        assert len(report["points"]) == 3
        assert len(report["gaps"]) == 5

    def test_stalled_writer(self, fake_repo: Path):
        now = 1793612000.0  # 5600s after stroke
        strokes = fake_repo / "data" / "strokes.jsonl"
        entry = json.dumps({
            "seq": 1,
            "at": "2026-11-02T08:00:00+00:00",
            "kind": "thought",
            "text": "old",
        })
        strokes.write_text(entry + "\n", encoding="utf-8")

        commit_mock = MagicMock(returncode=0, stdout="1793606450\n")
        push_mock = MagicMock(returncode=0, stdout="1793606400\n")

        def side_effect(cmd, **kw):
            if "refs/remotes" in " ".join(cmd):
                return push_mock
            return commit_mock

        with patch("pipeline_timeline.subprocess.run", side_effect=side_effect):
            report = build_timeline(fake_repo, now=now)

        assert report["overall"] in ("degraded", "stalled")

    def test_no_strokes_file(self, fake_repo: Path):
        """No strokes.jsonl → unknown status."""
        # fake_repo fixture doesn't create strokes.jsonl, so just don't create it
        commit_mock = MagicMock(returncode=0, stdout="1793606450\n")
        push_mock = MagicMock(returncode=0, stdout="1793606400\n")

        def side_effect(cmd, **kw):
            if "refs/remotes" in " ".join(cmd):
                return push_mock
            return commit_mock

        with patch("pipeline_timeline.subprocess.run", side_effect=side_effect):
            report = build_timeline(fake_repo, now=1793606500.0)

        # stroke_to_now gap will be unknown
        stroke_gap = report["gaps"][0]
        assert stroke_gap["name"] == "stroke_to_now"
        assert stroke_gap["status"] == "unknown"

    def test_report_has_now_timestamp(self, fake_repo: Path):
        strokes = fake_repo / "data" / "strokes.jsonl"
        strokes.write_text("", encoding="utf-8")
        with patch("pipeline_timeline.subprocess.run",
                    return_value=MagicMock(returncode=128, stdout="")):
            report = build_timeline(fake_repo, now=1793606500.0)
        assert "now" in report
        assert "2026" in report["now"]

    def test_worst_gap_is_reported(self, fake_repo: Path):
        strokes = fake_repo / "data" / "strokes.jsonl"
        entry = json.dumps({
            "seq": 1,
            "at": "2026-11-02T08:00:00+00:00",
            "kind": "thought",
            "text": "test",
        })
        strokes.write_text(entry + "\n", encoding="utf-8")

        # Make push very old
        commit_mock = MagicMock(returncode=0, stdout="1793606400\n")
        push_mock = MagicMock(returncode=0, stdout="1793592000\n")  # 4h old

        def side_effect(cmd, **kw):
            if "refs/remotes" in " ".join(cmd):
                return push_mock
            return commit_mock

        with patch("pipeline_timeline.subprocess.run", side_effect=side_effect):
            report = build_timeline(fake_repo, now=1793606500.0)

        assert report["worst_gap"] is not None


# ---------------------------------------------------------------------------
# integration: build_timeline with real-ish data
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_healthy_pipeline(self, fake_repo: Path):
        """Simulate a healthy pipeline and verify all gaps are healthy."""
        now = 1793606500.0
        strokes = fake_repo / "data" / "strokes.jsonl"
        # Stroke 30s ago
        entry = json.dumps({
            "seq": 100,
            "at": "2026-11-02T08:01:10+00:00",  # ~1730534470
            "kind": "thought",
            "text": "integration test",
        })
        strokes.write_text(entry + "\n", encoding="utf-8")

        # Commit 20s ago, push 40s ago
        commit_mock = MagicMock(returncode=0, stdout="1793606480\n")
        push_mock = MagicMock(returncode=0, stdout="1793606460\n")

        def side_effect(cmd, **kw):
            if "refs/remotes" in " ".join(cmd):
                return push_mock
            return commit_mock

        with patch("pipeline_timeline.subprocess.run", side_effect=side_effect):
            report = build_timeline(fake_repo, now=now)

        assert report["overall"] == "healthy"
        for g in report["gaps"]:
            assert g["status"] in ("healthy", "unknown")

    def test_stalled_push_detected(self, fake_repo: Path):
        """Simulate a pipeline where push hasn't happened in hours."""
        now = 1793606500.0
        strokes = fake_repo / "data" / "strokes.jsonl"
        entry = json.dumps({
            "seq": 100,
            "at": "2026-11-02T08:01:10+00:00",
            "kind": "thought",
            "text": "push stalled",
        })
        strokes.write_text(entry + "\n", encoding="utf-8")

        # Recent commit, very old push
        commit_mock = MagicMock(returncode=0, stdout="1793606480\n")
        push_mock = MagicMock(returncode=0, stdout="1793592000\n")  # 4h old

        def side_effect(cmd, **kw):
            if "refs/remotes" in " ".join(cmd):
                return push_mock
            return commit_mock

        with patch("pipeline_timeline.subprocess.run", side_effect=side_effect):
            report = build_timeline(fake_repo, now=now)

        push_gap = [g for g in report["gaps"] if g["name"] == "push_to_now"][0]
        assert push_gap["status"] in ("degraded", "stalled")
