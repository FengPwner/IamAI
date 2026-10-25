"""Tests for caretaker_handoff module."""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.caretaker_handoff import (
    build_handoff,
    handoff_summary,
    _load_recent_strokes,
    _count_total_strokes,
    _parse_iso,
)


@pytest.fixture
def temp_repo():
    """Create a temporary repo structure with a strokes log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        data_dir = repo / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"

        # Write some test strokes
        now = datetime.now(timezone.utc)
        strokes = []
        for i in range(60):  # More than default window of 50
            stroke = {
                "seq": 3000 + i,
                "at": (now - timedelta(minutes=60 - i)).isoformat(),
                "kind": ["thought", "devlog", "garden", "snippet", "metrics", "note"][i % 6],
                "text": f"Test stroke {i} with some content here -- measured now: {i * 10} lines"
            }
            strokes.append(json.dumps(stroke))

        strokes_file.write_text("\n".join(strokes), encoding="utf-8")
        yield repo


def test_build_handoff_basic(temp_repo):
    """Test basic handoff generation."""
    ho = build_handoff(repo_root=temp_repo, window=50)

    assert ho["total_strokes"] == 60
    assert ho["window"] == 50
    assert isinstance(ho["kind_dist"], dict)
    assert len(ho["kind_dist"]) > 0
    assert isinstance(ho["avg_length"], float)
    assert ho["avg_length"] > 0
    assert isinstance(ho["max_gap_s"], float)
    assert isinstance(ho["stall"], bool)
    assert "generated_at" in ho
    assert "last_stroke_at" in ho


def test_build_handoff_kind_distribution(temp_repo):
    """Test that kind distribution is correctly computed."""
    ho = build_handoff(repo_root=temp_repo, window=50)

    # With 50 strokes and 6 kinds (cycling), we should see all 6 kinds
    # 50 strokes: 8 full cycles (48) + 2 extra = some kinds have 9, some 8
    assert sum(ho["kind_dist"].values()) == 50
    assert all(count > 0 for count in ho["kind_dist"].values())


def test_build_handoff_stall_detection(temp_repo):
    """Test stall detection when strokes are recent."""
    ho = build_handoff(repo_root=temp_repo, stall_threshold_s=3600)  # 1 hour

    # Strokes are within the last hour, so should not stall
    assert ho["stall"] is False


def test_build_handoff_stall_old(temp_repo):
    """Test stall detection when strokes are old."""
    ho = build_handoff(repo_root=temp_repo, stall_threshold_s=60)  # 1 minute

    # Most recent stroke is ~1 minute old (60 - 59 minutes ago from now)
    # Actually the most recent is at now - timedelta(minutes=60-59) = now - 1 minute
    # So with threshold 60s, it should be borderline
    # Let's use a very small threshold
    ho = build_handoff(repo_root=temp_repo, stall_threshold_s=10)  # 10 seconds
    assert ho["stall"] is True


def test_build_handoff_missing_file():
    """Test handoff with missing strokes file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ho = build_handoff(repo_root=tmpdir)

        assert ho["total_strokes"] == 0
        assert ho["window"] == 0
        assert ho["kind_dist"] == {}
        assert ho["avg_length"] == 0.0
        assert ho["stall"] is False


def test_build_handoff_empty_file():
    """Test handoff with empty strokes file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        data_dir = repo / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes_file.write_text("", encoding="utf-8")

        ho = build_handoff(repo_root=repo)

        assert ho["total_strokes"] == 0
        assert ho["window"] == 0


def test_build_handoff_malformed_json():
    """Test handoff with malformed JSON lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        data_dir = repo / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"

        content = [
            '{"seq": 1, "at": "2026-10-16T06:00:00+00:00", "kind": "thought", "text": "valid"}',
            'this is not json',
            '{"seq": 2, "at": "2026-10-16T06:01:00+00:00", "kind": "devlog", "text": "also valid"}',
            '',
            '{"seq": 3, "at": "2026-10-16T06:02:00+00:00", "kind": "garden", "text": "third"}',
        ]
        strokes_file.write_text("\n".join(content), encoding="utf-8")

        ho = build_handoff(repo_root=repo, window=10)

        assert ho["total_strokes"] == 4  # Counts all non-empty lines (empty line excluded)
        assert ho["window"] == 3  # Only valid JSON parsed


def test_load_recent_strokes_window(temp_repo):
    """Test that window parameter limits the number of strokes."""
    strokes = _load_recent_strokes(temp_repo, window=10)
    assert len(strokes) == 10

    strokes = _load_recent_strokes(temp_repo, window=100)
    assert len(strokes) == 60  # Only 60 exist


def test_count_total_strokes(temp_repo):
    """Test total stroke counting."""
    count = _count_total_strokes(temp_repo)
    assert count == 60


def test_parse_iso_formats():
    """Test ISO timestamp parsing with various formats."""
    # Standard format with +00:00
    dt = _parse_iso("2026-10-16T06:00:00+00:00")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 16

    # Format with Z
    dt = _parse_iso("2026-10-16T06:00:00Z")
    assert dt.year == 2026

    # Format with +0000 (no colon)
    dt = _parse_iso("2026-10-16T06:00:00+0000")
    assert dt.year == 2026


def test_handoff_summary():
    """Test human-readable summary generation."""
    ho = {
        "total_strokes": 3014,
        "window": 50,
        "stall": False,
        "kind_dist": {"thought": 12, "devlog": 10, "garden": 8},
        "avg_length": 95.3,
        "max_gap_s": 120.0,
        "last_stroke_at": "2026-10-16T06:16:44+00:00",
        "commit_count": 5,
        "generated_at": "2026-10-16T07:00:00+00:00"
    }

    summary = handoff_summary(ho)

    assert "3014 strokes" in summary
    assert "50 in window" in summary
    assert "5 commits" in summary
    assert "no stall" in summary
    assert "thought=12" in summary
    assert "devlog=10" in summary


def test_handoff_summary_stall():
    """Test summary with stall flag."""
    ho = {
        "total_strokes": 100,
        "window": 10,
        "stall": True,
        "kind_dist": {"thought": 5},
        "avg_length": 50.0,
        "max_gap_s": 600.0,
        "last_stroke_at": "2026-10-16T05:00:00+00:00",
        "commit_count": 2,
        "generated_at": "2026-10-16T06:00:00+00:00"
    }

    summary = handoff_summary(ho)
    assert "STALL" in summary


def test_build_handoff_max_gap(temp_repo):
    """Test max gap calculation."""
    ho = build_handoff(repo_root=temp_repo, window=50)

    # Strokes are 1 minute apart, so max gap should be ~60s
    assert ho["max_gap_s"] > 0
    assert ho["max_gap_s"] < 120  # Should be close to 60s


def test_build_handoff_json_serializable(temp_repo):
    """Test that handoff dict is JSON-serializable."""
    ho = build_handoff(repo_root=temp_repo)

    # Should not raise
    json_str = json.dumps(ho)
    assert isinstance(json_str, str)

    # Should round-trip
    ho2 = json.loads(json_str)
    assert ho2["total_strokes"] == ho["total_strokes"]
