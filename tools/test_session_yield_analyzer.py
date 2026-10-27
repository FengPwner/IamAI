#!/usr/bin/env python3
"""test_session_yield_analyzer.py — tests for session yield analysis tool."""

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "session_yield_analyzer.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run_tool(*args: str, strokes_path: str | None = None) -> tuple[int, str]:
    """Run the tool as a subprocess and return (exit_code, stdout)."""
    cmd = [sys.executable, str(TOOL)] + list(args)
    if strokes_path:
        cmd.extend(["--strokes", strokes_path])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    return result.returncode, result.stdout.strip()


def make_strokes_file(sessions: list[list[dict]], tmpdir: Path) -> Path:
    """Create a strokes.jsonl with multiple sessions separated by gaps.

    Each element in `sessions` is a list of stroke dicts for one session.
    Between sessions, timestamps jump by 10 minutes (well above the
    default 300s gap threshold).
    """
    path = tmpdir / "test_strokes.jsonl"
    lines = []
    base = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    seq = 1

    for session_idx, session_strokes in enumerate(sessions):
        # gap between sessions: 10 minutes
        session_start = base + timedelta(minutes=session_idx * 10)
        for i, stroke in enumerate(session_strokes):
            ts = session_start + timedelta(seconds=i * 15)  # 15s cadence
            entry = {
                "seq": seq,
                "at": ts.isoformat(),
                "kind": stroke.get("kind", "thought"),
                "text": stroke.get("text", f"stroke {seq}"),
            }
            lines.append(json.dumps(entry))
            seq += 1

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# subprocess integration tests
# ---------------------------------------------------------------------------


class TestSubprocess:
    """Run the tool against the live repo and verify output shape."""

    def test_runs_successfully(self):
        """Tool should produce output and a valid exit code."""
        code, out = run_tool()
        assert code in (0, 1, 2), f"unexpected exit code: {code}"
        assert len(out) > 0, "tool produced no output"

    def test_human_output_has_header(self):
        """Human-readable output should contain the analysis header."""
        _, out = run_tool()
        if "ERROR" not in out:
            assert "session yield analysis" in out.lower()

    def test_json_output_is_valid(self):
        """JSON mode should produce parseable JSON with required fields."""
        code, out = run_tool("--json")
        if code == 2:
            pytest.skip("no strokes data available")
        data = json.loads(out)
        assert "total_sessions" in data
        assert "total_strokes" in data
        assert "reliability_score" in data
        assert "severity" in data
        assert data["severity"] in ("RELIABLE", "DEGRADED", "FRAGILE")
        assert isinstance(data["reliability_score"], float)
        assert 0.0 <= data["reliability_score"] <= 1.0

    def test_json_sessions_list(self):
        """JSON output should include a sessions list with session dicts."""
        code, out = run_tool("--json")
        if code == 2:
            pytest.skip("no strokes data available")
        data = json.loads(out)
        assert "sessions" in data
        assert isinstance(data["sessions"], list)
        if data["sessions"]:
            s = data["sessions"][0]
            assert "start" in s
            assert "end" in s
            assert "duration_seconds" in s
            assert "stroke_count" in s
            assert "strokes_per_minute" in s
            assert "kinds" in s

    def test_last_n_flag(self):
        """--last should limit the number of sessions analysed."""
        code, out = run_tool("--json", "--last", "5")
        if code == 2:
            pytest.skip("no strokes data available")
        data = json.loads(out)
        assert data["total_sessions"] <= 5

    def test_gap_threshold_flag(self):
        """--gap-threshold should be accepted without error."""
        code, out = run_tool("--gap-threshold", "600")
        assert code in (0, 1, 2)


# ---------------------------------------------------------------------------
# unit tests — synthetic data
# ---------------------------------------------------------------------------


class TestSessionDetection:
    """Test session detection against synthetic stroke data."""

    def test_single_session(self, tmp_path):
        """Strokes with no large gaps should form one session."""
        # create a session with 15 strokes (above MIN_STROKES_RELIABLE=10)
        strokes = [{"kind": "thought", "text": f"s{i}"} for i in range(15)]
        path = make_strokes_file([strokes], tmp_path)
        code, out = run_tool("--json", strokes_path=str(path))
        assert code == 0
        data = json.loads(out)
        assert data["total_sessions"] == 1
        assert data["total_strokes"] == 15
        assert data["reliability_score"] == 1.0  # 15 >= MIN_STROKES_RELIABLE (10)

    def test_two_sessions(self, tmp_path):
        """Two sessions separated by a gap should be detected."""
        session_a = [{"kind": "thought", "text": f"a{i}"} for i in range(15)]
        session_b = [{"kind": "metric", "text": f"b{i}"} for i in range(20)]
        path = make_strokes_file([session_a, session_b], tmp_path)
        code, out = run_tool("--json", strokes_path=str(path))
        assert code == 0
        data = json.loads(out)
        assert data["total_sessions"] == 2
        assert data["total_strokes"] == 35

    def test_many_sessions_productivity(self, tmp_path):
        """Most sessions with 10+ strokes should give high reliability."""
        sessions = [
            [{"kind": "thought", "text": f"s{s}i{i}"} for i in range(20)]
            for s in range(5)
        ]
        path = make_strokes_file(sessions, tmp_path)
        code, out = run_tool("--json", strokes_path=str(path))
        assert code == 0
        data = json.loads(out)
        assert data["total_sessions"] == 5
        assert data["reliability_score"] == 1.0  # all sessions have 20 strokes
        assert data["severity"] == "RELIABLE"

    def test_fragile_sessions(self, tmp_path):
        """Many short sessions should produce FRAGILE severity."""
        # 8 short sessions (3 strokes each) + 2 productive ones (20 each)
        sessions = []
        for i in range(8):
            sessions.append([{"kind": "thought", "text": f"short{i}"} for _ in range(3)])
        for i in range(2):
            sessions.append([{"kind": "metric", "text": f"long{i}"} for _ in range(20)])
        path = make_strokes_file(sessions, tmp_path)
        code, out = run_tool("--json", strokes_path=str(path))
        data = json.loads(out)
        assert data["severity"] == "FRAGILE"
        assert code == 1  # FRAGILE exits with 1

    def test_mixed_sessions_degraded(self, tmp_path):
        """A mix of short and long sessions should give DEGRADED."""
        sessions = []
        for i in range(4):
            sessions.append([{"kind": "thought", "text": f"s{i}"} for _ in range(3)])
        for i in range(6):
            sessions.append([{"kind": "metric", "text": f"l{i}"} for _ in range(15)])
        path = make_strokes_file(sessions, tmp_path)
        code, out = run_tool("--json", strokes_path=str(path))
        data = json.loads(out)
        assert data["severity"] == "DEGRADED"
        assert data["reliability_score"] == 0.6  # 6/10 productive

    def test_empty_file(self, tmp_path):
        """An empty strokes file should return exit code 2."""
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        code, out = run_tool("--json", strokes_path=str(path))
        assert code == 2

    def test_missing_file(self, tmp_path):
        """A non-existent file should return exit code 2."""
        code, out = run_tool("--json", strokes_path=str(tmp_path / "nope.jsonl"))
        assert code == 2


# ---------------------------------------------------------------------------
# unit tests — severity classification
# ---------------------------------------------------------------------------


class TestSeverityClassification:
    """Test the severity thresholds directly."""

    def test_reliable_at_80(self):
        from session_yield_analyzer import classify_severity
        assert classify_severity(0.80) == "RELIABLE"
        assert classify_severity(0.95) == "RELIABLE"
        assert classify_severity(1.0) == "RELIABLE"

    def test_degraded_at_50(self):
        from session_yield_analyzer import classify_severity
        assert classify_severity(0.50) == "DEGRADED"
        assert classify_severity(0.79) == "DEGRADED"

    def test_fragile_below_50(self):
        from session_yield_analyzer import classify_severity
        assert classify_severity(0.49) == "FRAGILE"
        assert classify_severity(0.0) == "FRAGILE"


# ---------------------------------------------------------------------------
# unit tests — yield trend
# ---------------------------------------------------------------------------


class TestYieldTrend:
    """Test the yield trend computation."""

    def _make_session(self, count: int, start: datetime) -> "Session":
        from session_yield_analyzer import Session
        strokes = [{"seq": i, "at": start.isoformat(), "kind": "thought", "text": "x"} for i in range(count)]
        end = start + timedelta(seconds=count * 15)
        return Session(start_time=start, end_time=end, strokes=strokes)

    def test_positive_trend(self):
        """More strokes in recent sessions → positive trend."""
        from session_yield_analyzer import compute_yield_trend
        base = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        # previous 10: 10 strokes each; recent 10: 20 strokes each
        sessions = []
        for i in range(10):
            sessions.append(self._make_session(10, base + timedelta(hours=i)))
        for i in range(10):
            sessions.append(self._make_session(20, base + timedelta(hours=10 + i)))
        trend = compute_yield_trend(sessions, window=10)
        assert trend > 0  # +100% improvement

    def test_negative_trend(self):
        """Fewer strokes in recent sessions → negative trend."""
        from session_yield_analyzer import compute_yield_trend
        base = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        sessions = []
        for i in range(10):
            sessions.append(self._make_session(20, base + timedelta(hours=i)))
        for i in range(10):
            sessions.append(self._make_session(10, base + timedelta(hours=10 + i)))
        trend = compute_yield_trend(sessions, window=10)
        assert trend < 0

    def test_insufficient_data(self):
        """Fewer than 2*window sessions → trend is 0."""
        from session_yield_analyzer import compute_yield_trend
        base = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        sessions = [self._make_session(10, base + timedelta(hours=i)) for i in range(5)]
        trend = compute_yield_trend(sessions, window=10)
        assert trend == 0.0

    def test_stable_trend(self):
        """Same stroke count → trend is 0."""
        from session_yield_analyzer import compute_yield_trend
        base = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        sessions = [self._make_session(15, base + timedelta(hours=i)) for i in range(20)]
        trend = compute_yield_trend(sessions, window=10)
        assert trend == 0.0


# ---------------------------------------------------------------------------
# unit tests — Session dataclass
# ---------------------------------------------------------------------------


class TestSessionDataclass:
    """Test the Session dataclass properties."""

    def test_duration(self):
        from session_yield_analyzer import Session
        start = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 25, 12, 30, 0, tzinfo=timezone.utc)
        s = Session(start_time=start, end_time=end, strokes=[{"kind": "thought"}] * 5)
        assert s.duration_seconds == 1800.0

    def test_strokes_per_minute(self):
        from session_yield_analyzer import Session
        start = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 25, 12, 10, 0, tzinfo=timezone.utc)
        s = Session(start_time=start, end_time=end, strokes=[{"kind": "thought"}] * 40)
        assert s.strokes_per_minute == 4.0

    def test_kind_breakdown(self):
        from session_yield_analyzer import Session
        strokes = [
            {"kind": "thought"},
            {"kind": "thought"},
            {"kind": "metric"},
            {"kind": "snippet"},
        ]
        s = Session(
            start_time=datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 10, 25, 12, 5, 0, tzinfo=timezone.utc),
            strokes=strokes,
        )
        assert s.kind_breakdown == {"thought": 2, "metric": 1, "snippet": 1}

    def test_to_dict(self):
        from session_yield_analyzer import Session
        s = Session(
            start_time=datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 10, 25, 12, 5, 0, tzinfo=timezone.utc),
            strokes=[{"kind": "thought"}] * 10,
        )
        d = s.to_dict()
        assert "start" in d
        assert "end" in d
        assert "duration_seconds" in d
        assert d["stroke_count"] == 10
        assert d["strokes_per_minute"] == pytest.approx(2.0, abs=0.1)

    def test_zero_duration(self):
        """A session with a single stroke has zero duration."""
        from session_yield_analyzer import Session
        ts = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        s = Session(start_time=ts, end_time=ts, strokes=[{"kind": "thought"}])
        assert s.duration_seconds == 0.0
        assert s.strokes_per_minute == 0.0


# ---------------------------------------------------------------------------
# unit tests — human-readable formatting
# ---------------------------------------------------------------------------


class TestHumanFormat:
    """Test the format_human function."""

    def test_error_format(self):
        from session_yield_analyzer import format_human
        out = format_human({"error": "no data"})
        assert "ERROR" in out
        assert "no data" in out

    def test_normal_format(self):
        from session_yield_analyzer import format_human
        data = {
            "total_sessions": 10,
            "total_strokes": 200,
            "median_session_duration_seconds": 1800.0,
            "median_strokes_per_session": 20,
            "productive_sessions": 8,
            "short_lived_sessions": 2,
            "reliability_score": 0.80,
            "severity": "RELIABLE",
            "yield_trend": 0.05,
            "gap_threshold_seconds": 300,
            "sessions": [],
        }
        out = format_human(data)
        assert "RELIABLE" in out
        assert "10" in out
        assert "200" in out
        assert "+5.0%" in out

    def test_negative_trend_format(self):
        from session_yield_analyzer import format_human
        data = {
            "total_sessions": 5,
            "total_strokes": 50,
            "median_session_duration_seconds": 600.0,
            "median_strokes_per_session": 10,
            "productive_sessions": 3,
            "short_lived_sessions": 2,
            "reliability_score": 0.60,
            "severity": "DEGRADED",
            "yield_trend": -0.25,
            "gap_threshold_seconds": 300,
            "sessions": [],
        }
        out = format_human(data)
        assert "DEGRADED" in out
        assert "-25.0%" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
