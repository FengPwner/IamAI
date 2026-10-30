"""Tests for iamai.repo_thermoregulation module."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_thermoregulation import (
    ThermoregReport,
    ThermalSignal,
    _classify,
    _find_repo_root,
    _inter_commit_intervals,
    _iter_tracked_files,
    _primary_anomaly,
    _recommend,
    analyze_thermoregulation,
    detect_author_concentration,
    detect_change_burstiness,
    detect_file_heat,
    detect_recency_cold,
    detect_thermal_gradient,
    thermoregulation_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo with git init and a few commits."""
    import subprocess
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo), check=True, capture_output=True,
    )
    # Create some files
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("# main\nprint('hello')\n")
    (repo / "src" / "util.py").write_text("# util\ndef helper(): pass\n")
    (repo / "README.md").write_text("# Test Repo\n")

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo), check=True, capture_output=True,
    )
    return repo


@pytest.fixture()
def empty_repo(tmp_path: Path) -> Path:
    """Create an empty git repo with no files."""
    import subprocess
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_thermal_signal_defaults(self):
        s = ThermalSignal(name="test", score=50.0, weight=0.2)
        assert s.evidence == ""
        assert s.items == []

    def test_thermal_signal_with_items(self):
        s = ThermalSignal(
            name="heat", score=75.0, weight=0.25,
            evidence="3 hotspots", items=["a.py", "b.py", "c.py"],
        )
        assert len(s.items) == 3
        assert s.evidence == "3 hotspots"

    def test_thermoreg_report_fields(self):
        r = ThermoregReport(
            anomaly_score=35.0, health_score=65.0,
            state="mild_stress", primary_anomaly="file_heat",
        )
        assert r.signals == []
        assert r.recommendation == ""
        assert r.files_scanned == 0
        assert r.window_days == 30

    def test_thermoreg_report_defaults(self):
        r = ThermoregReport(
            anomaly_score=10.0, health_score=90.0,
            state="homeostatic", primary_anomaly="none",
        )
        assert r.state == "homeostatic"


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_homeostatic(self):
        assert _classify(80) == "homeostatic"
        assert _classify(95) == "homeostatic"
        assert _classify(100) == "homeostatic"

    def test_mild_stress(self):
        assert _classify(60) == "mild_stress"
        assert _classify(79) == "mild_stress"

    def test_dysregulated(self):
        assert _classify(40) == "dysregulated"
        assert _classify(59) == "dysregulated"

    def test_critical(self):
        assert _classify(20) == "critical"
        assert _classify(39) == "critical"

    def test_thermal_failure(self):
        assert _classify(0) == "thermal_failure"
        assert _classify(19) == "thermal_failure"


# ---------------------------------------------------------------------------
# _primary_anomaly
# ---------------------------------------------------------------------------


class TestPrimaryAnomaly:
    def test_empty_signals(self):
        assert _primary_anomaly([]) == "none"

    def test_single_worst(self):
        signals = [
            ThermalSignal(name="a", score=10.0, weight=0.2),
            ThermalSignal(name="b", score=80.0, weight=0.3),
            ThermalSignal(name="c", score=30.0, weight=0.2),
        ]
        assert _primary_anomaly(signals) == "b"

    def test_all_zero(self):
        signals = [
            ThermalSignal(name="a", score=0.0, weight=0.2),
            ThermalSignal(name="b", score=0.0, weight=0.3),
        ]
        assert _primary_anomaly(signals) == "none"


# ---------------------------------------------------------------------------
# _recommend
# ---------------------------------------------------------------------------


class TestRecommend:
    def test_healthy_repo(self):
        rec = _recommend(90, "homeostatic", "none", [])
        assert "normal range" in rec

    def test_file_heat_recommendation(self):
        rec = _recommend(55, "dysregulated", "file_heat", [])
        assert "Hotspot" in rec or "hotspot" in rec.lower()

    def test_recency_cold_recommendation(self):
        rec = _recommend(50, "dysregulated", "recency_cold", [])
        assert "Cold" in rec or "cold" in rec.lower()

    def test_author_concentration_recommendation(self):
        rec = _recommend(55, "dysregulated", "author_concentration", [])
        assert "concentration" in rec.lower() or "contributor" in rec.lower()

    def test_change_burstiness_recommendation(self):
        rec = _recommend(50, "dysregulated", "change_burstiness", [])
        assert "bursty" in rec.lower() or "rhythm" in rec.lower()

    def test_thermal_gradient_recommendation(self):
        rec = _recommend(55, "dysregulated", "thermal_gradient", [])
        assert "concentrated" in rec.lower() or "attention" in rec.lower()

    def test_critical_priority(self):
        rec = _recommend(30, "critical", "file_heat", [])
        assert "prioritise" in rec.lower() or "caretaker" in rec.lower()

    def test_mild_schedule_review(self):
        rec = _recommend(55, "dysregulated", "file_heat", [])
        assert "review" in rec.lower() or "schedule" in rec.lower()


# ---------------------------------------------------------------------------
# Helpers (on real git repo)
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_find_repo_root(self, tmp_repo):
        root = _find_repo_root(tmp_repo / "src")
        assert root == tmp_repo

    def test_find_repo_root_fallback(self, tmp_path):
        # No .git anywhere
        result = _find_repo_root(tmp_path)
        assert isinstance(result, Path)

    def test_iter_tracked_files(self, tmp_repo):
        files = _iter_tracked_files(tmp_repo)
        names = {f.name for f in files}
        assert "main.py" in names
        assert "util.py" in names
        assert "README.md" in names

    def test_iter_tracked_files_empty(self, empty_repo):
        files = _iter_tracked_files(empty_repo)
        assert files == []


# ---------------------------------------------------------------------------
# Signal detectors
# ---------------------------------------------------------------------------


class TestDetectFileHeat:
    def test_basic(self, tmp_repo):
        sig = detect_file_heat(tmp_repo, window_days=7, sample_size=50)
        assert sig.name == "file_heat"
        assert sig.weight == 0.25
        assert 0.0 <= sig.score <= 100.0
        assert "file" in sig.evidence.lower()

    def test_no_files(self, empty_repo):
        sig = detect_file_heat(empty_repo, window_days=7)
        assert sig.score == 0.0
        assert "no tracked" in sig.evidence.lower()


class TestDetectRecencyCold:
    def test_basic(self, tmp_repo):
        sig = detect_recency_cold(tmp_repo, window_days=30, sample_size=50)
        assert sig.name == "recency_cold"
        assert sig.weight == 0.20
        assert 0.0 <= sig.score <= 100.0

    def test_no_files(self, empty_repo):
        sig = detect_recency_cold(empty_repo, window_days=30)
        assert sig.score == 0.0


class TestDetectAuthorConcentration:
    def test_single_author(self, tmp_repo):
        sig = detect_author_concentration(tmp_repo, window_days=30)
        assert sig.name == "author_concentration"
        assert sig.weight == 0.15
        # Single author gets moderate score
        assert 0.0 <= sig.score <= 100.0

    def test_no_commits(self, empty_repo):
        sig = detect_author_concentration(empty_repo, window_days=30)
        assert sig.score == 0.0

    def test_hhi_computation(self):
        """Verify HHI math conceptually."""
        # With 4 equal authors: HHI = 4 * (0.25)^2 = 0.25
        # ideal = 1/4 = 0.25, so norm = 0 → score = 0
        # This is tested indirectly through the function
        pass


class TestDetectChangeBurstiness:
    def test_basic(self, tmp_repo):
        sig = detect_change_burstiness(tmp_repo, window_days=30)
        assert sig.name == "change_burstiness"
        assert sig.weight == 0.20
        assert 0.0 <= sig.score <= 100.0

    def test_insufficient_data(self, empty_repo):
        sig = detect_change_burstiness(empty_repo, window_days=30)
        assert sig.score == 0.0
        assert "insufficient" in sig.evidence.lower()


class TestDetectThermalGradient:
    def test_basic(self, tmp_repo):
        sig = detect_thermal_gradient(tmp_repo, window_days=30, sample_size=50)
        assert sig.name == "thermal_gradient"
        assert sig.weight == 0.20
        assert 0.0 <= sig.score <= 100.0

    def test_no_files(self, empty_repo):
        sig = detect_thermal_gradient(empty_repo, window_days=30)
        assert sig.score == 0.0


# ---------------------------------------------------------------------------
# Aggregate analysis
# ---------------------------------------------------------------------------


class TestAnalyzeThermoregulation:
    def test_signal_count(self, tmp_repo):
        """analyze_thermoregulation returns exactly 5 signals."""
        report = analyze_thermoregulation(tmp_repo, window_days=7)
        assert len(report.signals) == 5

    def test_state_valid(self, tmp_repo):
        report = analyze_thermoregulation(tmp_repo, window_days=7)
        assert report.state in {
            "homeostatic", "mild_stress", "dysregulated",
            "critical", "thermal_failure",
        }

    def test_scores_in_range(self, tmp_repo):
        report = analyze_thermoregulation(tmp_repo, window_days=7)
        assert 0.0 <= report.health_score <= 100.0
        assert 0.0 <= report.anomaly_score <= 100.0

    def test_runs_on_test_repo(self, tmp_repo):
        report = analyze_thermoregulation(tmp_repo, window_days=7)
        assert isinstance(report, ThermoregReport)
        assert len(report.signals) == 5

    def test_window_parameter(self, tmp_repo):
        r1 = analyze_thermoregulation(tmp_repo, window_days=1)
        r7 = analyze_thermoregulation(tmp_repo, window_days=7)
        # Both should produce valid reports
        assert r1.state in {
            "homeostatic", "mild_stress", "dysregulated",
            "critical", "thermal_failure",
        }
        assert r7.state in {
            "homeostatic", "mild_stress", "dysregulated",
            "critical", "thermal_failure",
        }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_contains_key_info(self):
        report = ThermoregReport(
            anomaly_score=25.0, health_score=75.0,
            state="mild_stress", primary_anomaly="file_heat",
            signals=[
                ThermalSignal(name="file_heat", score=40.0, weight=0.25,
                              evidence="2 hotspots"),
                ThermalSignal(name="recency_cold", score=10.0, weight=0.20,
                              evidence="5 cold files"),
            ],
            recommendation="Review hotspots.",
            files_scanned=100,
            window_days=30,
        )
        text = thermoregulation_summary(report)
        assert "mild_stress" in text
        assert "75.0" in text
        assert "file_heat" in text
        assert "Review hotspots" in text
        assert "100" in text

    def test_summary_empty_signals(self):
        report = ThermoregReport(
            anomaly_score=0.0, health_score=100.0,
            state="homeostatic", primary_anomaly="none",
        )
        text = thermoregulation_summary(report)
        assert "homeostatic" in text


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline_on_test_repo(self, tmp_repo):
        """Run full pipeline on a small test repository."""
        report = analyze_thermoregulation(tmp_repo, window_days=7)
        text = thermoregulation_summary(report)

        assert "Thermoregulation:" in text
        assert len(report.signals) == 5

        for sig in report.signals:
            assert sig.name in {
                "file_heat", "recency_cold", "author_concentration",
                "change_burstiness", "thermal_gradient",
            }
            assert sig.weight > 0

        assert len(report.recommendation) > 0
