"""Tests for iamai.stroke_gap_spectrum — gap frequency distribution analysis."""

import math

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.stroke_gap_spectrum import (
    GapSpectrumReport,
    analyse_gap_spectrum,
    analyse_strokes_file,
    _assign_bin,
    _cadence_adherence,
    _compute_gaps,
    _extract_timestamps,
    _spectral_entropy,
    _spectral_uniformity,
    DEFAULT_BIN_EDGES,
    DEFAULT_BIN_LABELS,
    DEFAULT_TARGET_CADENCE,
)


# ── helpers ────────────────────────────────────────────────────────────

def _stroke(at_iso: str, seq: int = 1, kind: str = "thought") -> dict:
    return {"seq": seq, "at": at_iso, "kind": kind, "text": "sample stroke"}


def _stroke_ts(ts: float, seq: int = 1) -> dict:
    return {"seq": seq, "ts": ts, "kind": "note", "text": "ts stroke"}


def _make_strokes_iso(intervals_sec: list[float], start: str = "2026-01-01T00:00:00+00:00") -> list[dict]:
    """Build a list of strokes with given intervals (seconds) between them."""
    base = datetime.fromisoformat(start)
    strokes = [_stroke(base.isoformat(), seq=0)]
    current = base
    for i, gap in enumerate(intervals_sec, 1):
        current = current + timedelta(seconds=gap)
        strokes.append(_stroke(current.isoformat(), seq=i))
    return strokes


def _make_strokes_ts(intervals_sec: list[float], start: float = 1000.0) -> list[dict]:
    """Build strokes using numeric timestamps."""
    strokes = [_stroke_ts(start, seq=0)]
    current = start
    for i, gap in enumerate(intervals_sec, 1):
        current += gap
        strokes.append(_stroke_ts(current, seq=i))
    return strokes


def _write_jsonl(strokes: list, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")


# ── _extract_timestamps ──────────────────────────────────────────────

class TestExtractTimestamps:
    def test_iso_format(self):
        strokes = [_stroke("2026-01-01T00:00:00+00:00"), _stroke("2026-01-01T00:01:00+00:00")]
        ts = _extract_timestamps(strokes)
        assert len(ts) == 2
        assert ts[1] - ts[0] == pytest.approx(60.0, abs=1)

    def test_numeric_ts(self):
        strokes = [_stroke_ts(1000.0), _stroke_ts(1015.0)]
        ts = _extract_timestamps(strokes)
        assert ts == [1000.0, 1015.0]

    def test_mixed_prefers_ts(self):
        strokes = [{"seq": 1, "ts": 500.0, "at": "2026-01-01T00:00:00+00:00"}]
        ts = _extract_timestamps(strokes)
        assert ts == [500.0]

    def test_empty(self):
        ts = _extract_timestamps([])
        assert ts == []


# ── _compute_gaps ────────────────────────────────────────────────────

class TestComputeGaps:
    def test_positive_gaps(self):
        gaps = _compute_gaps([100.0, 115.0, 130.0])
        assert gaps == [15.0, 15.0]

    def test_negative_skipped(self):
        gaps = _compute_gaps([100.0, 90.0, 110.0])
        assert gaps == [20.0]

    def test_single_timestamp(self):
        gaps = _compute_gaps([100.0])
        assert gaps == []

    def test_empty(self):
        gaps = _compute_gaps([])
        assert gaps == []


# ── _assign_bin ──────────────────────────────────────────────────────

class TestAssignBin:
    def test_first_bin(self):
        label = _assign_bin(5.0, DEFAULT_BIN_EDGES, DEFAULT_BIN_LABELS)
        assert label == '0-10s'

    def test_middle_bin(self):
        label = _assign_bin(45.0, DEFAULT_BIN_EDGES, DEFAULT_BIN_LABELS)
        assert label == '30-60s'

    def test_last_bin(self):
        label = _assign_bin(7200.0, DEFAULT_BIN_EDGES, DEFAULT_BIN_LABELS)
        assert label == '60min+'

    def test_boundary_low(self):
        label = _assign_bin(0.0, DEFAULT_BIN_EDGES, DEFAULT_BIN_LABELS)
        assert label == '0-10s'

    def test_boundary_exact(self):
        label = _assign_bin(10.0, DEFAULT_BIN_EDGES, DEFAULT_BIN_LABELS)
        assert label == '10-30s'


# ── _spectral_entropy ────────────────────────────────────────────────

class TestSpectralEntropy:
    def test_uniform_distribution(self):
        # 7 bins, uniform
        fracs = {f'bin{i}': 1/7 for i in range(7)}
        entropy = _spectral_entropy(fracs)
        assert entropy == pytest.approx(math.log2(7), rel=1e-6)

    def test_concentrated_distribution(self):
        # All in one bin
        fracs = {'bin0': 1.0, 'bin1': 0.0, 'bin2': 0.0}
        entropy = _spectral_entropy(fracs)
        assert entropy == 0.0

    def test_two_bins(self):
        fracs = {'bin0': 0.5, 'bin1': 0.5}
        entropy = _spectral_entropy(fracs)
        assert entropy == pytest.approx(1.0, rel=1e-6)


# ── _spectral_uniformity ─────────────────────────────────────────────

class TestSpectralUniformity:
    def test_perfectly_uniform(self):
        fracs = {'bin0': 0.25, 'bin1': 0.25, 'bin2': 0.25, 'bin3': 0.25}
        uniformity = _spectral_uniformity(fracs)
        assert uniformity == pytest.approx(1.0, rel=1e-6)

    def test_all_in_one(self):
        fracs = {'bin0': 1.0, 'bin1': 0.0, 'bin2': 0.0, 'bin3': 0.0}
        uniformity = _spectral_uniformity(fracs)
        # Max deviation: 3 bins at -0.25, 1 bin at +0.75 = 1.5
        # Uniformity = 1 - 1.5/2 = 0.25
        assert uniformity == pytest.approx(0.25, rel=1e-6)

    def test_empty(self):
        uniformity = _spectral_uniformity({})
        assert uniformity == 0.0


# ── _cadence_adherence ───────────────────────────────────────────────

class TestCadenceAdherence:
    def test_all_within_tolerance(self):
        gaps = [14.0, 15.0, 16.0, 14.5]
        adherence = _cadence_adherence(gaps, target=15.0, tolerance=0.5)
        assert adherence == pytest.approx(1.0)

    def test_none_within_tolerance(self):
        gaps = [5.0, 60.0, 300.0]
        adherence = _cadence_adherence(gaps, target=15.0, tolerance=0.5)
        assert adherence == 0.0

    def test_half_within_tolerance(self):
        gaps = [15.0, 15.0, 60.0, 60.0]
        adherence = _cadence_adherence(gaps, target=15.0, tolerance=0.5)
        assert adherence == pytest.approx(0.5)

    def test_empty(self):
        adherence = _cadence_adherence([], target=15.0)
        assert adherence == 0.0


# ── analyse_gap_spectrum ─────────────────────────────────────────────

class TestAnalyseGapSpectrum:
    def test_uniform_15s_cadence(self):
        strokes = _make_strokes_ts([15.0] * 10)
        report = analyse_gap_spectrum(strokes, target_cadence=15.0)
        
        assert report.total_strokes == 11
        assert report.total_gaps == 10
        assert report.mean_gap == pytest.approx(15.0)
        assert report.median_gap == pytest.approx(15.0)
        assert report.dominant_bin == '10-30s'
        assert report.dominant_fraction == 1.0
        assert report.cadence_adherence == 1.0
        assert report.spectral_entropy == 0.0  # All in one bin

    def test_mixed_cadence(self):
        strokes = _make_strokes_ts([15.0, 60.0, 300.0, 15.0, 60.0])
        report = analyse_gap_spectrum(strokes, target_cadence=15.0)
        
        assert report.total_gaps == 5
        assert report.bin_counts['10-30s'] == 2
        assert report.bin_counts['1-5min'] == 2   # 60.0 x2
        assert report.bin_counts['5-15min'] == 1  # 300.0 x1
        assert report.cadence_adherence < 1.0
        assert report.spectral_entropy > 0.0

    def test_empty_strokes(self):
        report = analyse_gap_spectrum([])
        assert report.total_strokes == 0
        assert report.total_gaps == 0

    def test_single_stroke(self):
        strokes = [_stroke_ts(1000.0)]
        report = analyse_gap_spectrum(strokes)
        assert report.total_strokes == 1
        assert report.total_gaps == 0

    def test_two_strokes(self):
        strokes = _make_strokes_ts([15.0])
        report = analyse_gap_spectrum(strokes, target_cadence=15.0)
        assert report.total_gaps == 1
        assert report.cadence_adherence == 1.0

    def test_iso_timestamps(self):
        strokes = _make_strokes_iso([15.0, 15.0, 15.0])
        report = analyse_gap_spectrum(strokes, target_cadence=15.0)
        assert report.total_gaps == 3
        assert report.cadence_adherence == 1.0

    def test_custom_bins(self):
        strokes = _make_strokes_ts([5.0, 25.0, 100.0])
        edges = [0, 10, 50, 200]
        labels = ['short', 'medium', 'long']
        report = analyse_gap_spectrum(strokes, bin_edges=edges, bin_labels=labels, target_cadence=15.0)
        
        assert report.bin_counts['short'] == 1
        assert report.bin_counts['medium'] == 1
        assert report.bin_counts['long'] == 1

    def test_bin_count_mismatch(self):
        strokes = _make_strokes_ts([15.0])
        with pytest.raises(ValueError):
            analyse_gap_spectrum(strokes, bin_edges=[0, 10, 20], bin_labels=['a'])


# ── GapSpectrumReport ────────────────────────────────────────────────

class TestGapSpectrumReport:
    def test_to_dict(self):
        report = GapSpectrumReport(
            total_strokes=10,
            total_gaps=9,
            bin_counts={'bin0': 5, 'bin1': 4},
            bin_fractions={'bin0': 0.556, 'bin1': 0.444},
            dominant_bin='bin0',
            dominant_fraction=0.556,
            spectral_entropy=1.0,
            spectral_uniformity=0.8,
            cadence_adherence=0.75,
            mean_gap=15.0,
            median_gap=14.5,
        )
        d = report.to_dict()
        assert d['total_strokes'] == 10
        assert d['dominant_bin'] == 'bin0'
        assert d['spectral_entropy'] == 1.0

    def test_classify_concentrated_excellent(self):
        report = GapSpectrumReport(spectral_entropy=1.0, cadence_adherence=0.9)
        c = report.classify()
        assert c['concentration'] == 'concentrated'
        assert c['tracking'] == 'excellent'

    def test_classify_moderate_spread_moderate(self):
        report = GapSpectrumReport(spectral_entropy=2.0, cadence_adherence=0.65)
        c = report.classify()
        assert c['concentration'] == 'moderate_spread'
        assert c['tracking'] == 'moderate'

    def test_classify_dispersed_poor(self):
        report = GapSpectrumReport(spectral_entropy=3.0, cadence_adherence=0.3)
        c = report.classify()
        assert c['concentration'] == 'dispersed'
        assert c['tracking'] == 'poor'


# ── analyse_strokes_file ─────────────────────────────────────────────

class TestAnalyseStrokesFile:
    def test_file_analysis(self, tmp_path):
        strokes = _make_strokes_ts([15.0] * 5)
        path = tmp_path / "strokes.jsonl"
        _write_jsonl(strokes, path)
        
        report = analyse_strokes_file(path, target_cadence=15.0)
        assert report.total_strokes == 6
        assert report.total_gaps == 5
        assert report.cadence_adherence == 1.0

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        
        report = analyse_strokes_file(path)
        assert report.total_strokes == 0
        assert report.total_gaps == 0


# ── integration ──────────────────────────────────────────────────────

class TestIntegration:
    def test_realistic_cadence_drift(self):
        """Simulate realistic writer with occasional drift."""
        gaps = (
            [15.0] * 10 +      # Normal operation
            [60.0] * 3 +       # Minor drift
            [15.0] * 5 +       # Recovery
            [300.0] * 2 +      # Major stall
            [15.0] * 8         # Recovery
        )
        strokes = _make_strokes_ts(gaps)
        report = analyse_gap_spectrum(strokes, target_cadence=15.0)
        
        assert report.total_gaps == len(gaps)
        assert report.bin_counts['10-30s'] == 23  # 10+5+8
        assert report.bin_counts['1-5min'] == 3   # 60.0 x3
        assert report.bin_counts['5-15min'] == 2  # 300.0 x2
        assert 0.5 < report.cadence_adherence < 1.0
        assert report.spectral_entropy > 0.0

    def test_extreme_burst_pattern(self):
        """Simulate burst-then-stall behaviour."""
        gaps = [1.0] * 20 + [3600.0] * 5  # Burst then stall
        strokes = _make_strokes_ts(gaps)
        report = analyse_gap_spectrum(strokes, target_cadence=15.0)
        
        assert report.bin_counts['0-10s'] == 20
        assert report.bin_counts['60min+'] == 5
        assert report.cadence_adherence == 0.0
        assert report.spectral_entropy > 0.5
