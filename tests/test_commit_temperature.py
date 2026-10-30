"""tests for iamai.commit_temperature"""

import pytest

from iamai.commit_temperature import (
    COOL_THRESHOLD,
    HOT_THRESHOLD,
    WARM_THRESHOLD,
    CommitThermometer,
    TemperatureReport,
    classify,
    _compute_heat_index,
)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------
class TestClassify:
    def test_hot(self):
        assert classify(1.0) == "hot"
        assert classify(0.60) == "hot"
        assert classify(0.85) == "hot"

    def test_warm(self):
        assert classify(0.30) == "warm"
        assert classify(0.59) == "warm"
        assert classify(0.45) == "warm"

    def test_cool(self):
        assert classify(0.10) == "cool"
        assert classify(0.29) == "cool"
        assert classify(0.15) == "cool"

    def test_cold(self):
        assert classify(0.0) == "cold"
        assert classify(0.09) == "cold"
        assert classify(0.05) == "cold"

    def test_boundary_values(self):
        # Exactly at thresholds
        assert classify(HOT_THRESHOLD) == "hot"
        assert classify(WARM_THRESHOLD) == "warm"
        assert classify(COOL_THRESHOLD) == "cool"

        # Just below thresholds
        assert classify(HOT_THRESHOLD - 0.001) == "warm"
        assert classify(WARM_THRESHOLD - 0.001) == "cool"
        assert classify(COOL_THRESHOLD - 0.001) == "cold"


# ---------------------------------------------------------------------------
# CommitThermometer — basic ingestion
# ---------------------------------------------------------------------------
class TestIngestion:
    def test_ingest_file_lists(self):
        t = CommitThermometer()
        t.ingest_file_lists([["a.py", "b.py"], ["a.py"]])
        assert t.commit_count == 2

    def test_ingest_diffs(self):
        t = CommitThermometer()
        t.ingest_diffs([
            {"files": ["a.py", "b.py"]},
            {"files": ["c.md"]},
        ])
        assert t.commit_count == 2

    def test_ingest_diffs_missing_key(self):
        t = CommitThermometer()
        t.ingest_diffs([{"files": ["a.py"]}, {"other": "data"}, {"files": []}])
        # Only the first one has a non-empty files list
        assert t.commit_count == 1

    def test_empty_ingestion(self):
        t = CommitThermometer()
        assert t.commit_count == 0

    def test_reset(self):
        t = CommitThermometer()
        t.ingest_file_lists([["a.py"]])
        assert t.commit_count == 1
        t.reset()
        assert t.commit_count == 0


# ---------------------------------------------------------------------------
# report() — empty state
# ---------------------------------------------------------------------------
class TestEmptyReport:
    def test_no_data(self):
        t = CommitThermometer()
        r = t.report()
        assert r.window == 0
        assert r.total_files == 0
        assert r.temperatures == {}
        assert r.hot_files == []
        assert r.heat_index == 0.0


# ---------------------------------------------------------------------------
# report() — temperatures
# ---------------------------------------------------------------------------
class TestTemperatures:
    def setup_method(self):
        self.t = CommitThermometer()
        # 4 commits:
        #   commit 1: a.py, b.py
        #   commit 2: a.py, c.md
        #   commit 3: a.py
        #   commit 4: a.py, b.py
        self.t.ingest_file_lists([
            ["a.py", "b.py"],
            ["a.py", "c.md"],
            ["a.py"],
            ["a.py", "b.py"],
        ])

    def test_window_all(self):
        r = self.t.report()
        assert r.window == 4
        assert r.total_files == 3
        # a.py: 4/4 = 1.0, b.py: 2/4 = 0.5, c.md: 1/4 = 0.25
        assert r.temperatures["a.py"] == pytest.approx(1.0)
        assert r.temperatures["b.py"] == pytest.approx(0.5)
        assert r.temperatures["c.md"] == pytest.approx(0.25)

    def test_classifications(self):
        r = self.t.report()
        assert r.classifications["a.py"] == "hot"
        assert r.classifications["b.py"] == "warm"
        assert r.classifications["c.md"] == "cool"

    def test_hot_files(self):
        r = self.t.report()
        assert r.hot_files == ["a.py"]

    def test_warm_files(self):
        r = self.t.report()
        assert r.warm_files == ["b.py"]

    def test_cool_files(self):
        r = self.t.report()
        assert r.cool_files == ["c.md"]

    def test_cold_files(self):
        r = self.t.report()
        assert r.cold_files == []

    def test_window_subset(self):
        # Last 2 commits: a.py (2/2=1.0), b.py (1/2=0.5), c.md absent
        r = self.t.report(window=2)
        assert r.window == 2
        assert r.total_files == 2
        assert r.temperatures["a.py"] == pytest.approx(1.0)
        assert r.temperatures["b.py"] == pytest.approx(0.5)

    def test_window_larger_than_data(self):
        r = self.t.report(window=100)
        assert r.window == 4  # capped at actual count

    def test_single_commit(self):
        t = CommitThermometer()
        t.ingest_file_lists([["x.py", "y.py"]])
        r = t.report()
        assert r.window == 1
        assert r.temperatures["x.py"] == pytest.approx(1.0)
        assert r.temperatures["y.py"] == pytest.approx(1.0)

    def test_temperature_sorted_descending(self):
        r = self.t.report()
        temps = list(r.temperatures.values())
        assert temps == sorted(temps, reverse=True)

    def test_alphabetical_tiebreak(self):
        # b.py and c.md both appear once in last 2 commits... no wait
        # let's make a proper tie scenario
        t = CommitThermometer()
        t.ingest_file_lists([["z.py", "a.py", "m.py"]])
        r = t.report()
        names = list(r.temperatures.keys())
        # All have temperature 1.0, so sorted alphabetically
        assert names == ["a.py", "m.py", "z.py"]


# ---------------------------------------------------------------------------
# report() — heat index
# ---------------------------------------------------------------------------
class TestHeatIndex:
    def test_single_file(self):
        t = CommitThermometer()
        t.ingest_file_lists([["only.py"], ["only.py"], ["only.py"]])
        r = t.report()
        assert r.heat_index == pytest.approx(1.0)

    def test_uniform_distribution(self):
        # Each file appears exactly once across 3 commits
        t = CommitThermometer()
        t.ingest_file_lists([["a.py"], ["b.py"], ["c.py"]])
        r = t.report()
        # Perfectly uniform → heat_index should be 0
        assert r.heat_index == pytest.approx(0.0, abs=0.01)

    def test_concentrated(self):
        # One file in every commit, others rare
        t = CommitThermometer()
        t.ingest_file_lists([
            ["hot.py", "rare1.py"],
            ["hot.py", "rare2.py"],
            ["hot.py"],
        ])
        r = t.report()
        assert r.heat_index > 0.1  # concentrated (hot.py dominates)

    def test_empty_thermometer(self):
        assert _compute_heat_index({}) == 0.0


# ---------------------------------------------------------------------------
# shift()
# ---------------------------------------------------------------------------
class TestShift:
    def test_shift_detects_heating(self):
        t = CommitThermometer()
        # Old window (all 4): a=4/4, b=2/4, c=1/4
        # New window (last 2): a=2/2, b=1/2, c=absent
        t.ingest_file_lists([
            ["a.py", "b.py"],
            ["a.py", "c.md"],
            ["a.py"],
            ["a.py", "b.py"],
        ])
        shifts = t.shift(old_window=4, new_window=2)
        # c.md: old=0.25, new=0.0 → delta = -0.25
        assert "c.md" in shifts
        assert shifts["c.md"] < 0

    def test_shift_empty(self):
        t = CommitThermometer()
        shifts = t.shift(old_window=5, new_window=3)
        assert shifts == {}


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------
class TestToDict:
    def test_serialisation(self):
        t = CommitThermometer()
        t.ingest_file_lists([["a.py", "b.py"], ["a.py"]])
        r = t.report()
        d = r.to_dict()
        assert "window" in d
        assert "temperatures" in d
        assert "heat_index" in d
        assert isinstance(d["heat_index"], float)
        assert isinstance(d["hot_files"], list)

    def test_empty_to_dict(self):
        t = CommitThermometer()
        d = t.report().to_dict()
        assert d["window"] == 0
        assert d["temperatures"] == {}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_duplicate_files_in_commit(self):
        """A commit listing the same file twice should count as one touch."""
        t = CommitThermometer()
        t.ingest_file_lists([["a.py", "a.py", "a.py"]])
        r = t.report()
        # Dedup within a commit: a.py appears in 1/1 = 1.0
        assert r.temperatures["a.py"] == pytest.approx(1.0)

    def test_empty_commit(self):
        t = CommitThermometer()
        t.ingest_file_lists([[], ["a.py"], []])
        r = t.report()
        assert r.window == 3
        assert r.temperatures["a.py"] == pytest.approx(1 / 3)

    def test_large_window(self):
        t = CommitThermometer()
        commits = [["f.py"]] * 1000
        t.ingest_file_lists(commits)
        r = t.report(window=500)
        assert r.window == 500
        assert r.temperatures["f.py"] == pytest.approx(1.0)
