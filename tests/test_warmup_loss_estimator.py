"""Tests for warmup_loss_estimator snippet."""

from datetime import datetime, timedelta, timezone

from snippets.warmup_loss_estimator import (
    Generation,
    WarmupLossReport,
    estimate_warmup_loss,
    generation_timeline,
)


def test_generation_warmup_seconds():
    """Test warmup_seconds calculation."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gen = Generation(
        restart_time=now,
        first_stroke_time=now + timedelta(seconds=45),
        target_cadence=15,
    )
    assert gen.warmup_seconds == 45.0


def test_generation_warmup_seconds_no_stroke():
    """Test warmup_seconds when no stroke has been produced yet."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gen = Generation(
        restart_time=now,
        first_stroke_time=None,
        target_cadence=15,
    )
    assert gen.warmup_seconds == float("inf")


def test_generation_expected_strokes_in_hour():
    """Test expected_strokes_in_hour calculation."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gen = Generation(
        restart_time=now,
        first_stroke_time=now + timedelta(seconds=30),
        target_cadence=15,
    )
    assert gen.expected_strokes_in_hour == 240  # 3600 / 15


def test_generation_strokes_lost_in_warmup():
    """Test strokes_lost_in_warmup calculation."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gen = Generation(
        restart_time=now,
        first_stroke_time=now + timedelta(seconds=45),
        target_cadence=15,
        strokes_in_first_hour=200,
    )
    assert gen.strokes_lost_in_warmup == 3  # 45 / 15


def test_generation_stabilization_deficit():
    """Test stabilization_deficit calculation."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gen = Generation(
        restart_time=now,
        first_stroke_time=now + timedelta(seconds=30),
        target_cadence=15,
        strokes_in_first_hour=180,  # expected 240, so deficit = 60
    )
    assert gen.stabilization_deficit == 60


def test_estimate_warmup_loss_empty():
    """Test estimate_warmup_loss with no generations."""
    report = estimate_warmup_loss([])
    assert report.generations == 0
    assert report.total_warmup_seconds == 0.0
    assert report.total_strokes_lost == 0


def test_estimate_warmup_loss_single_generation():
    """Test estimate_warmup_loss with one generation."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gens = [
        Generation(
            restart_time=now,
            first_stroke_time=now + timedelta(seconds=45),
            target_cadence=15,
            strokes_in_first_hour=200,
        )
    ]
    report = estimate_warmup_loss(gens)
    assert report.generations == 1
    assert report.total_warmup_seconds == 45.0
    assert report.total_strokes_lost == 3
    assert report.mean_warmup_seconds == 45.0
    assert report.worst_warmup_seconds == 45.0


def test_estimate_warmup_loss_multiple_generations():
    """Test estimate_warmup_loss with multiple generations."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gens = [
        Generation(
            restart_time=now,
            first_stroke_time=now + timedelta(seconds=45),
            target_cadence=15,
            strokes_in_first_hour=200,
        ),
        Generation(
            restart_time=now + timedelta(hours=2),
            first_stroke_time=now + timedelta(hours=2, seconds=120),
            target_cadence=15,
            strokes_in_first_hour=150,
        ),
    ]
    report = estimate_warmup_loss(gens)
    assert report.generations == 2
    assert report.total_warmup_seconds == 165.0  # 45 + 120
    assert report.total_strokes_lost == 11  # 3 + 8
    assert report.mean_warmup_seconds == 82.5
    assert report.worst_warmup_seconds == 120.0


def test_warmup_loss_report_severity():
    """Test severity classification."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)

    # Negligible: avg warmup <= 30s
    gens_negligible = [
        Generation(
            restart_time=now,
            first_stroke_time=now + timedelta(seconds=20),
            target_cadence=15,
        )
    ]
    report_negligible = estimate_warmup_loss(gens_negligible)
    assert report_negligible.severity() == "negligible"

    # Moderate: avg warmup 30-120s
    gens_moderate = [
        Generation(
            restart_time=now,
            first_stroke_time=now + timedelta(seconds=60),
            target_cadence=15,
        )
    ]
    report_moderate = estimate_warmup_loss(gens_moderate)
    assert report_moderate.severity() == "moderate"

    # Significant: avg warmup 120-600s
    gens_significant = [
        Generation(
            restart_time=now,
            first_stroke_time=now + timedelta(seconds=300),
            target_cadence=15,
        )
    ]
    report_significant = estimate_warmup_loss(gens_significant)
    assert report_significant.severity() == "significant"

    # Severe: avg warmup > 600s
    gens_severe = [
        Generation(
            restart_time=now,
            first_stroke_time=now + timedelta(seconds=900),
            target_cadence=15,
        )
    ]
    report_severe = estimate_warmup_loss(gens_severe)
    assert report_severe.severity() == "severe"


def test_generation_timeline():
    """Test generation_timeline output format."""
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    gens = [
        Generation(
            restart_time=now,
            first_stroke_time=now + timedelta(seconds=45),
            target_cadence=15,
            strokes_in_first_hour=200,
        ),
        Generation(
            restart_time=now + timedelta(hours=2),
            first_stroke_time=now + timedelta(hours=2, seconds=120),
            target_cadence=15,
            strokes_in_first_hour=150,
        ),
    ]
    timeline = generation_timeline(gens)
    assert len(timeline) == 2
    assert timeline[0]["generation"] == 0
    assert timeline[0]["warmup_seconds"] == 45.0
    assert timeline[0]["strokes_lost"] == 3
    assert timeline[1]["generation"] == 1
    assert timeline[1]["warmup_seconds"] == 120.0
    assert timeline[1]["strokes_lost"] == 8
