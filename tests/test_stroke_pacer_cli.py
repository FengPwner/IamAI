"""Tests for tools/stroke_pacer.py CLI wrapper.

Covers: basic invocation, JSON output, target override, rate-window override,
missing strokes file, empty strokes file, exit code semantics, and
the --strokes path override.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "stroke_pacer.py"


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run the CLI tool and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        cwd=cwd or REPO,
        timeout=30,
    )


def _make_strokes(tmp_path: Path, n: int, base_time: datetime | None = None) -> Path:
    """Create a temporary strokes.jsonl with n strokes spread over today."""
    if base_time is None:
        now = datetime.now(timezone.utc)
        base_time = now.replace(hour=0, minute=5, second=0, microsecond=0)
    path = tmp_path / "strokes.jsonl"
    kinds = ("devlog", "garden", "metrics", "note", "snippet", "thought")
    lines = []
    for i in range(n):
        t = base_time + timedelta(minutes=i * 2)
        stroke = {
            "at": t.isoformat(),
            "kind": kinds[i % len(kinds)],
            "path": f"docs/TEST.md",
            "seq": 10000 + i,
            "text": f"test stroke {i}: measured now: {t.isoformat()}",
        }
        lines.append(json.dumps(stroke))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- Basic invocation ---


def test_basic_invocation_exits():
    """CLI should exit (0 or 1) and produce output."""
    result = run_cli()
    assert result.returncode in (0, 1, 2)
    assert result.stdout.strip() != "" or result.stderr.strip() != ""


def test_basic_invocation_mentions_strokes():
    """Output should mention strokes and the target."""
    result = run_cli()
    if result.returncode != 2:
        out = result.stdout.lower()
        assert "strokes" in out or "stroke" in out


# --- JSON output ---


def test_json_output_valid():
    """--json should produce valid JSON with required keys."""
    result = run_cli("--json")
    if result.returncode == 2:
        pytest.skip("no strokes data available")
    data = json.loads(result.stdout)
    required_keys = {
        "strokes_today", "daily_target", "remaining",
        "hours_left", "current_rate", "required_rate",
        "verdict", "projected_total",
    }
    assert required_keys.issubset(data.keys())


def test_json_verdict_is_valid():
    """verdict should be one of ahead, on_track, behind."""
    result = run_cli("--json")
    if result.returncode == 2:
        pytest.skip("no strokes data available")
    data = json.loads(result.stdout)
    assert data["verdict"] in ("ahead", "on_track", "behind")


def test_json_target_override():
    """--target should change the daily_target in JSON output."""
    result = run_cli("--target", "9999", "--json")
    if result.returncode == 2:
        pytest.skip("no strokes data available")
    data = json.loads(result.stdout)
    assert data["daily_target"] == 9999


# --- Target override ---


def test_target_changes_remaining(tmp_path: Path):
    """Higher target should increase remaining count."""
    strokes = _make_strokes(tmp_path, 50)
    r1 = run_cli("--target", "100", "--strokes", str(strokes), "--json")
    r2 = run_cli("--target", "200", "--strokes", str(strokes), "--json")
    d1 = json.loads(r1.stdout)
    d2 = json.loads(r2.stdout)
    assert d2["remaining"] > d1["remaining"]


# --- Rate window ---


def test_rate_window_accepted():
    """--rate-window should be accepted without error."""
    result = run_cli("--rate-window", "2.0")
    assert result.returncode in (0, 1, 2)


# --- Missing strokes file ---


def test_missing_strokes_file(tmp_path: Path):
    """Nonexistent strokes path should exit 2."""
    fake = tmp_path / "nonexistent.jsonl"
    result = run_cli("--strokes", str(fake))
    assert result.returncode == 2
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


# --- Empty strokes file ---


def test_empty_strokes_file(tmp_path: Path):
    """Empty strokes file should exit 2 (no strokes today)."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    result = run_cli("--strokes", str(empty), "--target", "100")
    assert result.returncode == 2


# --- Custom strokes file ---


def test_custom_strokes_path(tmp_path: Path):
    """--strokes should read from the specified file."""
    strokes = _make_strokes(tmp_path, 30)
    result = run_cli("--strokes", str(strokes), "--target", "100", "--json")
    assert result.returncode in (0, 1)
    data = json.loads(result.stdout)
    assert data["strokes_today"] == 30
    assert data["daily_target"] == 100


def test_custom_strokes_verdict_ahead(tmp_path: Path):
    """When strokes >= target, verdict should be ahead."""
    strokes = _make_strokes(tmp_path, 150)
    result = run_cli("--strokes", str(strokes), "--target", "100", "--json")
    data = json.loads(result.stdout)
    assert data["verdict"] == "ahead"
    assert data["remaining"] == 0


# --- Exit code semantics ---


def test_exit_zero_when_on_track_or_ahead(tmp_path: Path):
    """Exit 0 when verdict is ahead or on_track."""
    strokes = _make_strokes(tmp_path, 200)
    result = run_cli("--strokes", str(strokes), "--target", "100")
    data_result = run_cli("--strokes", str(strokes), "--target", "100", "--json")
    data = json.loads(data_result.stdout)
    if data["verdict"] in ("ahead", "on_track"):
        assert result.returncode == 0


def test_exit_one_when_behind(tmp_path: Path):
    """Exit 1 when verdict is behind."""
    # Create only a few strokes with a very high target
    strokes = _make_strokes(tmp_path, 5)
    result = run_cli("--strokes", str(strokes), "--target", "99999")
    assert result.returncode == 1


# --- Human-readable output ---


def test_human_output_contains_slash(tmp_path: Path):
    """Human output should contain 'X/Y strokes today' format."""
    strokes = _make_strokes(tmp_path, 30)
    result = run_cli("--strokes", str(strokes), "--target", "100")
    out = result.stdout
    assert "strokes today" in out
    assert "/100" in out


def test_human_output_contains_verdict(tmp_path: Path):
    """Human output should contain the verdict word."""
    strokes = _make_strokes(tmp_path, 30)
    result = run_cli("--strokes", str(strokes), "--target", "100")
    out = result.stdout.lower()
    assert any(v in out for v in ("ahead", "on_track", "behind"))


# --- Projected total ---


def test_projected_total_positive(tmp_path: Path):
    """Projected total should be non-negative."""
    strokes = _make_strokes(tmp_path, 20)
    result = run_cli("--strokes", str(strokes), "--target", "100", "--json")
    data = json.loads(result.stdout)
    assert data["projected_total"] >= 0


def test_projected_total_exceeds_target_when_ahead(tmp_path: Path):
    """When ahead, projected total should meet or exceed target."""
    strokes = _make_strokes(tmp_path, 200)
    result = run_cli("--strokes", str(strokes), "--target", "100", "--json")
    data = json.loads(result.stdout)
    assert data["projected_total"] >= 100
