"""Tests for heartbeat.health_check() — the four-state writer classifier.

health_check() takes a cadence result and the current gap since the last
stroke, and returns a verdict: healthy, degraded, dying, or dead.

The boundaries are:

- count < 2 and small gap → degraded (not enough data)
- count < 2 and gap > 4× cadence → dead
- gap > 4× cadence → dead regardless of cadence quality
- mean > 2× expected AND gap > 2× expected → dying
- jitter > 1.0 OR mean > 1.5× expected → degraded
- everything within bounds → healthy
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.heartbeat import health_check


def _cadence(every=15, count=20, mean_interval=15.0, std_interval=1.0, jitter=None):
    """Build a minimal cadence result dict."""
    if jitter is None:
        jitter = std_interval / every if every > 0 else 0.0
    return {
        "count": count,
        "mean_interval": mean_interval,
        "std_interval": std_interval,
        "jitter": jitter,
        "every": every,
        "degraded": jitter > 1.0 or mean_interval > every * 2,
    }


# --- healthy ---


def test_healthy_writer():
    """Low jitter, mean close to cadence, small gap → healthy."""
    cad = _cadence(every=15, count=50, mean_interval=15.2, std_interval=0.8)
    result = health_check(cad, gap_seconds=10.0)
    assert result["status"] == "healthy"
    assert result["confidence"] >= 0.9


def test_healthy_boundary():
    """Just below the degraded threshold → still healthy."""
    cad = _cadence(every=15, count=30, mean_interval=22.0, std_interval=1.0)
    # mean 22.0 < 1.5 * 15 = 22.5, jitter = 1.0/15 ≈ 0.067
    result = health_check(cad, gap_seconds=20.0)
    assert result["status"] == "healthy"


# --- degraded ---


def test_degraded_high_jitter():
    """Jitter > 1.0 pushes status to degraded even with reasonable mean."""
    cad = _cadence(every=15, count=30, mean_interval=16.0, std_interval=20.0, jitter=1.33)
    result = health_check(cad, gap_seconds=10.0)
    assert result["status"] == "degraded"


def test_degraded_mean_drift():
    """Mean interval > 1.5× expected → degraded."""
    cad = _cadence(every=15, count=30, mean_interval=25.0, std_interval=1.0)
    # 25.0 > 1.5 * 15 = 22.5
    result = health_check(cad, gap_seconds=10.0)
    assert result["status"] == "degraded"


def test_degraded_too_few_strokes_small_gap():
    """count < 2 with a small gap → degraded (not enough data, but not dead)."""
    cad = _cadence(every=15, count=1, mean_interval=0.0, std_interval=0.0, jitter=0.0)
    result = health_check(cad, gap_seconds=20.0)
    assert result["status"] == "degraded"
    assert "too few strokes" in result["reason"]


# --- dying ---


def test_dying_slow_and_growing():
    """Mean > 2× cadence AND gap > 2× cadence → dying."""
    cad = _cadence(every=15, count=20, mean_interval=35.0, std_interval=5.0)
    result = health_check(cad, gap_seconds=35.0)
    assert result["status"] == "dying"
    assert result["confidence"] >= 0.8


def test_dying_not_dead_yet():
    """Dying, not dead: gap is large but under 4× cadence."""
    cad = _cadence(every=15, count=10, mean_interval=40.0, std_interval=8.0)
    # gap 50s > 2*15=30, but < 4*15=60
    result = health_check(cad, gap_seconds=50.0)
    assert result["status"] == "dying"


# --- dead ---


def test_dead_gap_exceeds_4x():
    """Gap > 4× cadence → dead regardless of cadence quality."""
    cad = _cadence(every=15, count=100, mean_interval=15.0, std_interval=0.5)
    result = health_check(cad, gap_seconds=65.0)
    assert result["status"] == "dead"
    assert result["confidence"] >= 0.9


def test_dead_too_few_strokes_huge_gap():
    """count < 2 with gap > 4× cadence → dead."""
    cad = _cadence(every=15, count=0, mean_interval=0.0, std_interval=0.0, jitter=0.0)
    result = health_check(cad, gap_seconds=120.0)
    assert result["status"] == "dead"


def test_dead_overrides_dying():
    """When gap > 4× cadence, dead wins even if dying conditions also hold."""
    cad = _cadence(every=15, count=20, mean_interval=40.0, std_interval=10.0)
    result = health_check(cad, gap_seconds=100.0)
    assert result["status"] == "dead"


# --- structural ---


def test_result_has_required_keys():
    """Every result contains status, confidence, and reason."""
    cad = _cadence()
    result = health_check(cad, gap_seconds=10.0)
    assert "status" in result
    assert "confidence" in result
    assert "reason" in result
    assert 0.0 <= result["confidence"] <= 1.0


def test_status_is_known_value():
    """Status is always one of the four known states."""
    cad = _cadence()
    for gap in [0, 10, 30, 60, 120]:
        result = health_check(cad, gap_seconds=float(gap))
        assert result["status"] in ("healthy", "degraded", "dying", "dead")
