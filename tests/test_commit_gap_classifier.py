#!/usr/bin/env python3
"""Tests for commit_gap_classifier."""

import sys
import os
from datetime import datetime, timezone

# Add tools to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from commit_gap_classifier import classify_gap, analyze_gaps


def test_classify_normal():
    """Normal gap: <= 2x median."""
    assert classify_gap(100, 100, datetime(2026, 1, 1, 12, 0)) == "normal"
    assert classify_gap(150, 100, datetime(2026, 1, 1, 12, 0)) == "normal"
    assert classify_gap(200, 100, datetime(2026, 1, 1, 12, 0)) == "normal"


def test_classify_stretched():
    """Stretched gap: > 2x and <= 5x median."""
    assert classify_gap(250, 100, datetime(2026, 1, 1, 12, 0)) == "stretched"
    assert classify_gap(400, 100, datetime(2026, 1, 1, 12, 0)) == "stretched"
    assert classify_gap(500, 100, datetime(2026, 1, 1, 12, 0)) == "stretched"


def test_classify_stalled():
    """Stalled gap: > 5x median."""
    assert classify_gap(600, 100, datetime(2026, 1, 1, 12, 0)) == "stalled"
    assert classify_gap(1000, 100, datetime(2026, 1, 1, 12, 0)) == "stalled"


def test_classify_overnight():
    """Overnight stall: > 1 hour during 00:00-06:00."""
    # 2 hour gap at 3am
    assert classify_gap(7200, 600, datetime(2026, 1, 1, 3, 0)) == "overnight"
    # 1.5 hour gap at 5am
    assert classify_gap(5400, 600, datetime(2026, 1, 1, 5, 0)) == "overnight"
    # 1 hour gap at 2am (exactly 3600, not > 3600)
    assert classify_gap(3600, 600, datetime(2026, 1, 1, 2, 0)) != "overnight"


def test_classify_overnight_vs_stalled():
    """Overnight takes priority over stalled during early hours."""
    # 2 hour gap at 3am would be stalled (>5x median=600) but overnight wins
    assert classify_gap(7200, 600, datetime(2026, 1, 1, 3, 0)) == "overnight"
    # Same gap at noon is just stalled
    assert classify_gap(7200, 600, datetime(2026, 1, 1, 12, 0)) == "stalled"


def test_classify_boundary_conditions():
    """Test exact boundary conditions."""
    median = 100
    noon = datetime(2026, 1, 1, 12, 0)
    
    # Exactly 2x median: should be normal (<=2x)
    assert classify_gap(200, median, noon) == "normal"
    
    # Just over 2x: should be stretched
    assert classify_gap(201, median, noon) == "stretched"
    
    # Exactly 5x: should be stretched (<=5x)
    assert classify_gap(500, median, noon) == "stretched"
    
    # Just over 5x: should be stalled
    assert classify_gap(501, median, noon) == "stalled"


def test_analyze_gaps_insufficient_data():
    """Analyze with insufficient commits."""
    # This test depends on the actual git repo state
    # We'll just verify it doesn't crash
    classifications, median_gap, max_gap = analyze_gaps(limit=1)
    assert isinstance(classifications, list)
    assert isinstance(median_gap, float)
    assert isinstance(max_gap, float)


def test_analyze_gaps_structure():
    """Verify classification structure."""
    classifications, median_gap, max_gap = analyze_gaps(limit=10)
    
    if classifications:
        c = classifications[0]
        assert "gap_seconds" in c
        assert "classification" in c
        assert "timestamp" in c
        assert "hour" in c
        assert c["classification"] in ["normal", "stretched", "stalled", "overnight"]
        assert 0 <= c["hour"] <= 23


def test_median_calculation():
    """Verify median is calculated correctly."""
    classifications, median_gap, max_gap = analyze_gaps(limit=20)
    
    if len(classifications) >= 2:
        # Median should be reasonable
        assert median_gap > 0
        assert max_gap >= median_gap


def test_hour_extraction():
    """Verify hour is extracted from timestamp."""
    classifications, _, _ = analyze_gaps(limit=15)
    
    for c in classifications:
        assert "hour" in c
        assert 0 <= c["hour"] <= 23


def test_timestamp_format():
    """Verify timestamp is ISO format."""
    classifications, _, _ = analyze_gaps(limit=10)
    
    for c in classifications:
        ts = c["timestamp"]
        # Should be parseable as ISO format
        try:
            datetime.fromisoformat(ts)
        except ValueError:
            raise AssertionError(f"Invalid timestamp format: {ts}")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
