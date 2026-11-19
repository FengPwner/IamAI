"""Tests for commit_recovery_time module.

Covers: timestamp conversion, disruption detection, recovery measurement,
resilience scoring, classification, edge cases (few commits, no disruptions,
all disruptions, never-recovered), severity analysis, serialisation, and
boundary conditions.  38 test functions.

Written by Qwen during caretaker visit 724, 2026-11-19.
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from iamai.commit_recovery_time import (
    DisruptionEvent,
    RecoveryReport,
    _classify,
    _measure_recovery,
    _to_epoch,
    _zero_report,
    analyse_recovery,
    analyse_recovery_by_severity,
)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestToEpoch:
    def test_epoch_int(self):
        assert _to_epoch(1000) == 1000.0

    def test_epoch_float(self):
        assert _to_epoch(1234.5) == 1234.5

    def test_datetime_naive(self):
        dt = datetime(2026, 1, 1, 0, 0, 0)
        expected = dt.replace(tzinfo=timezone.utc).timestamp()
        assert _to_epoch(dt) == expected

    def test_datetime_aware(self):
        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert _to_epoch(dt) == dt.timestamp()

    def test_iso_string_with_z(self):
        ts = "2026-01-01T00:00:00Z"
        result = _to_epoch(ts)
        expected = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_iso_string_with_offset(self):
        ts = "2026-07-01T12:00:00+08:00"
        result = _to_epoch(ts)
        expected = datetime(
            2026, 7, 1, 12, 0, 0,
            tzinfo=timezone(timedelta(hours=8))
        ).timestamp()
        assert result == expected

    def test_iso_string_naive(self):
        ts = "2026-03-15T10:30:00"
        result = _to_epoch(ts)
        expected = datetime(2026, 3, 15, 10, 30, 0, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            _to_epoch("not-a-timestamp")

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            _to_epoch([1, 2, 3])


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify:
    def test_resilient(self):
        assert _classify(0.80) == "resilient"
        assert _classify(0.95) == "resilient"
        assert _classify(1.0) == "resilient"

    def test_moderate(self):
        assert _classify(0.50) == "moderate"
        assert _classify(0.79) == "moderate"

    def test_fragile(self):
        assert _classify(0.25) == "fragile"
        assert _classify(0.49) == "fragile"

    def test_brittle(self):
        assert _classify(0.0) == "brittle"
        assert _classify(0.24) == "brittle"

    def test_boundary_values(self):
        assert _classify(0.80) == "resilient"
        assert _classify(0.50) == "moderate"
        assert _classify(0.25) == "fragile"


# ---------------------------------------------------------------------------
# Zero report
# ---------------------------------------------------------------------------

class TestZeroReport:
    def test_zero_report_defaults(self):
        r = _zero_report(5)
        assert r.n_commits == 5
        assert r.n_gaps == 0
        assert r.disruption_count == 0
        assert r.classification == "resilient"
        assert r.resilience_score == 1.0

    def test_zero_report_with_target(self):
        r = _zero_report(10, target=600.0)
        assert r.target_cadence_seconds == 600.0


# ---------------------------------------------------------------------------
# Recovery measurement (internal helper)
# ---------------------------------------------------------------------------

class TestMeasureRecovery:
    def test_immediate_recovery(self):
        # Target 60s; disruption at index 2 (gap=300s); then 3 normal gaps
        gaps = [60, 60, 300, 55, 65, 60, 58]
        commits, recovered = _measure_recovery(gaps, 2, 60.0, 20)
        assert recovered is True
        assert commits == 3  # gaps at indices 3, 4, 5 are all within [30, 120]

    def test_delayed_recovery(self):
        # Disruption at 0, then one more anomaly, then recovery
        gaps = [300, 200, 50, 55, 60]  # target=60, 200 is still anomalous
        commits, recovered = _measure_recovery(gaps, 0, 60.0, 20)
        # gap[1]=200 > 120 → resets counter; gaps[2,3,4] are normal → 3 commits from idx 2
        assert recovered is True
        assert commits == 4  # checked 4 gaps (idx 1,2,3,4), recovered on 4th

    def test_never_recovered(self):
        # All subsequent gaps are anomalous
        gaps = [300, 200, 150, 200, 180]
        commits, recovered = _measure_recovery(gaps, 0, 60.0, 20)
        assert recovered is False
        assert commits is None

    def test_max_window_limit(self):
        # Recovery happens at commit 25 but max window is 10
        gaps = [300] + [200] * 15 + [60, 60, 60]
        commits, recovered = _measure_recovery(gaps, 0, 60.0, 10)
        assert recovered is False
        assert commits is None

    def test_end_of_sequence(self):
        # Disruption near end, not enough gaps to recover
        gaps = [60, 60, 300]
        commits, recovered = _measure_recovery(gaps, 2, 60.0, 20)
        assert recovered is False
        assert commits is None


# ---------------------------------------------------------------------------
# DisruptionEvent
# ---------------------------------------------------------------------------

class TestDisruptionEvent:
    def test_to_dict(self):
        d = DisruptionEvent(index=5, gap_seconds=1800.5, recovery_commits=3, recovered=True)
        result = d.to_dict()
        assert result["index"] == 5
        assert result["gap_seconds"] == 1800.5
        assert result["recovery_commits"] == 3
        assert result["recovered"] is True

    def test_to_dict_never_recovered(self):
        d = DisruptionEvent(index=10, gap_seconds=3600.0, recovery_commits=None, recovered=False)
        result = d.to_dict()
        assert result["recovery_commits"] is None
        assert result["recovered"] is False


# ---------------------------------------------------------------------------
# RecoveryReport serialisation
# ---------------------------------------------------------------------------

class TestRecoveryReport:
    def test_to_dict_empty(self):
        r = RecoveryReport(
            n_commits=10,
            n_gaps=9,
            target_cadence_seconds=600.0,
            disruption_count=0,
        )
        d = r.to_dict()
        assert d["n_commits"] == 10
        assert d["disruption_count"] == 0
        assert d["disruptions"] == []

    def test_to_dict_with_disruptions(self):
        r = RecoveryReport(
            n_commits=20,
            n_gaps=19,
            target_cadence_seconds=600.0,
            disruption_count=2,
            disruptions=[
                DisruptionEvent(0, 2400.0, 3, True),
                DisruptionEvent(10, 3600.0, None, False),
            ],
            mean_recovery_commits=3.0,
            median_recovery_commits=3.0,
            max_recovery_commits=3,
            resilience_score=0.5,
            never_recovered=1,
            classification="moderate",
        )
        d = r.to_dict()
        assert len(d["disruptions"]) == 2
        assert d["never_recovered"] == 1
        assert d["classification"] == "moderate"


# ---------------------------------------------------------------------------
# analyse_recovery — main function
# ---------------------------------------------------------------------------

class TestAnalyseRecovery:
    def test_few_commits(self):
        """Fewer than 3 commits returns zero report."""
        result = analyse_recovery([1000, 2000])
        assert result.n_commits == 2
        assert result.disruption_count == 0

    def test_empty_input(self):
        result = analyse_recovery([])
        assert result.n_commits == 0

    def test_single_commit(self):
        result = analyse_recovery([1000])
        assert result.n_commits == 1

    def test_no_disruptions(self):
        """All gaps within normal range → no disruptions, resilient."""
        # 20 commits at exactly 60s apart
        timestamps = [i * 60 for i in range(20)]
        result = analyse_recovery(timestamps, target_seconds=60.0)
        assert result.disruption_count == 0
        assert result.classification == "resilient"
        assert result.resilience_score == 1.0

    def test_all_identical_timestamps(self):
        """All same timestamp → zero target → zero report."""
        ts = [1000] * 10
        result = analyse_recovery(ts)
        assert result.target_cadence_seconds == 0.0
        assert result.classification == "resilient"

    def test_single_disruption_with_recovery(self):
        """One disruption that recovers quickly."""
        # Normal cadence ~60s, one 300s gap, then back to normal
        timestamps = [0, 60, 120, 180, 480, 540, 600, 660, 720]
        result = analyse_recovery(timestamps, target_seconds=60.0, disruption_multiplier=3.0)
        assert result.disruption_count == 1
        assert result.disruptions[0].recovered is True
        assert result.classification == "resilient"

    def test_single_disruption_no_recovery(self):
        """One disruption followed by continued instability."""
        # After the disruption, gaps keep being anomalous
        timestamps = [0, 60, 120, 180, 600, 900, 1200, 1500, 1800]
        result = analyse_recovery(timestamps, target_seconds=60.0, disruption_multiplier=3.0)
        assert result.disruption_count >= 1
        # At least the first disruption should not recover (subsequent gaps are 300s each)
        assert any(not d.recovered for d in result.disruptions)

    def test_multiple_disruptions_mixed_recovery(self):
        """Several disruptions, some recover, some don't."""
        ts = [
            0, 60, 120,     # normal (gaps: 60, 60)
            600,             # disruption (480s gap, >300 threshold at 5x)
            660, 720, 780,  # recovery (gaps: 60, 60, 60)
            1200,            # disruption (420s gap)
            1500, 1800, 2100, 2400,  # no recovery (all 300s gaps, ==300 not >300)
        ]
        result = analyse_recovery(ts, target_seconds=60.0, disruption_multiplier=5.0)
        assert result.disruption_count == 2
        recovered = [d for d in result.disruptions if d.recovered]
        not_recovered = [d for d in result.disruptions if not d.recovered]
        assert len(recovered) == 1
        assert len(not_recovered) == 1

    def test_resilience_score_calculation(self):
        """Verify resilience score is computed correctly."""
        # Use 5x multiplier → threshold = 300s. Disruptions are 400s gaps.
        # Recovery band = [30, 120]. Non-recovery anomalous gaps = 150s (< 300, not disruptions).
        base = [0]
        # Disruption 1: 400s gap → then 3 normal gaps (recover in 3)
        base.append(base[-1] + 400)
        base.append(base[-1] + 60)
        base.append(base[-1] + 55)
        base.append(base[-1] + 65)
        # Disruption 2: 400s gap → then 3 normal gaps (recover in 3)
        base.append(base[-1] + 400)
        base.append(base[-1] + 58)
        base.append(base[-1] + 62)
        base.append(base[-1] + 60)
        # Disruption 3: 400s gap → then slow recovery (reset by 150s gap)
        base.append(base[-1] + 400)
        base.append(base[-1] + 150)  # anomalous (150 > 120), resets counter, but not a disruption (150 < 300)
        base.append(base[-1] + 55)
        base.append(base[-1] + 60)
        base.append(base[-1] + 58)
        # Disruption 4: 400s gap → never recovers (all 150s gaps)
        base.append(base[-1] + 400)
        base.append(base[-1] + 150)
        base.append(base[-1] + 150)
        base.append(base[-1] + 150)

        result = analyse_recovery(base, target_seconds=60.0, disruption_multiplier=5.0, resilience_threshold=5)
        assert result.disruption_count == 4
        # Disruptions 1,2 recover in 3 commits (within 5); disruption 3 recovers in 5 (150 resets, then 3 normal = 5 total, within 5); disruption 4 never recovers
        # So 3 out of 4 → resilience = 0.75
        assert result.resilience_score == pytest.approx(0.75, abs=0.01)
        assert result.classification == "moderate"

    def test_explicit_target_vs_auto(self):
        """Explicit target_seconds overrides median-based estimation."""
        timestamps = [i * 100 for i in range(20)]
        # Median gap = 100
        r_auto = analyse_recovery(timestamps)
        assert r_auto.target_cadence_seconds == pytest.approx(100.0, abs=1.0)

        # Override with 60
        r_explicit = analyse_recovery(timestamps, target_seconds=60.0)
        assert r_explicit.target_cadence_seconds == 60.0
        # With target=60, 100s gaps may be disruptions (100 > 60*3=180? No, 100 < 180)
        # So no disruptions either way in this case

    def test_disruption_multiplier_effect(self):
        """Lower multiplier detects more disruptions."""
        timestamps = [0, 60, 120, 300, 360, 420, 480]
        # Gap of 180s between 120 and 300
        r_strict = analyse_recovery(timestamps, target_seconds=60.0, disruption_multiplier=2.0)
        r_loose = analyse_recovery(timestamps, target_seconds=60.0, disruption_multiplier=5.0)
        # With 2x: 180 > 120 → disruption; with 5x: 180 < 300 → no disruption
        assert r_strict.disruption_count >= 1
        assert r_loose.disruption_count == 0

    def test_iso_timestamps(self):
        """Works with ISO-8601 string timestamps."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        timestamps = [
            (base + timedelta(seconds=i * 60)).isoformat()
            for i in range(10)
        ]
        # Insert a disruption
        timestamps.append((base + timedelta(seconds=600 + 600)).isoformat())
        timestamps.append((base + timedelta(seconds=600 + 600 + 60)).isoformat())
        timestamps.append((base + timedelta(seconds=600 + 600 + 120)).isoformat())
        timestamps.append((base + timedelta(seconds=600 + 600 + 180)).isoformat())

        result = analyse_recovery(timestamps, target_seconds=60.0)
        assert result.disruption_count >= 1

    def test_datetime_objects(self):
        """Works with datetime objects directly."""
        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        timestamps = [base + timedelta(seconds=i * 60) for i in range(10)]
        result = analyse_recovery(timestamps, target_seconds=60.0)
        assert result.disruption_count == 0

    def test_unsorted_timestamps(self):
        """Function should handle unsorted input by sorting internally."""
        timestamps = [600, 0, 120, 60, 180, 240, 300]
        result = analyse_recovery(timestamps, target_seconds=60.0)
        assert result.n_commits == 7
        assert result.n_gaps == 6

    def test_max_recovery_window_respected(self):
        """Disruptions beyond max_recovery_window are never recovered."""
        # Disruption at index 2, then 25 anomalous gaps before recovery
        base = [0, 60, 120]
        # Big gap
        base.append(120 + 600)
        # 25 slightly-anomalous gaps (130s each, target=60, range=[30,120])
        for i in range(25):
            base.append(base[-1] + 130)
        # Then 3 normal gaps
        for i in range(3):
            base.append(base[-1] + 60)

        result = analyse_recovery(base, target_seconds=60.0, max_recovery_window=10)
        # Should not recover within 10 commits
        first_disruption = result.disruptions[0]
        assert first_disruption.recovered is False

    def test_resilience_threshold_effect(self):
        """Lower threshold makes resilience score stricter."""
        ts = [
            0, 60, 120, 180,  # normal
            600,               # disruption (420s)
            660, 720, 780, 840, 900,  # recover in 5
            1500,              # disruption (600s)
            1560, 1620, 1680,  # recover in 3
        ]
        r_strict = analyse_recovery(ts, target_seconds=60.0, resilience_threshold=3)
        r_loose = analyse_recovery(ts, target_seconds=60.0, resilience_threshold=10)
        # With threshold=3, the 5-commit recovery doesn't count → lower score
        assert r_strict.resilience_score <= r_loose.resilience_score


# ---------------------------------------------------------------------------
# Severity analysis
# ---------------------------------------------------------------------------

class TestAnalyseRecoveryBySeverity:
    def test_few_commits(self):
        result = analyse_recovery_by_severity([1000, 2000])
        assert result == {}

    def test_no_disruptions(self):
        timestamps = [i * 60 for i in range(20)]
        result = analyse_recovery_by_severity(timestamps, target_seconds=60.0)
        # No disruptions in any band → empty dict (or all bands absent)
        assert isinstance(result, dict)

    def test_mixed_severity(self):
        """Create disruptions of different magnitudes."""
        ts = [0]
        # Normal gaps of 60s
        for i in range(5):
            ts.append(ts[-1] + 60)
        # Mild disruption: 200s gap (3.3x)
        ts.append(ts[-1] + 200)
        for i in range(3):
            ts.append(ts[-1] + 60)
        # Severe disruption: 700s gap (11.7x)
        ts.append(ts[-1] + 700)
        for i in range(3):
            ts.append(ts[-1] + 60)

        result = analyse_recovery_by_severity(ts, target_seconds=60.0)
        assert isinstance(result, dict)
        # Should have at least one severity band with disruptions
        total_disruptions = sum(r.disruption_count for r in result.values())
        assert total_disruptions >= 1

    def test_custom_severity_levels(self):
        """Custom severity levels create different bands."""
        ts = [i * 60 for i in range(10)]
        ts.append(ts[-1] + 150)  # 2.5x of 60
        ts.extend([ts[-1] + 60] * 5)

        result = analyse_recovery_by_severity(
            ts, target_seconds=60.0, severity_levels=[2.0, 4.0]
        )
        assert isinstance(result, dict)

    def test_all_same_timestamps(self):
        ts = [1000] * 10
        result = analyse_recovery_by_severity(ts)
        assert result == {}
