#!/usr/bin/env python3
"""Tests for tools/repo_temperature.py — single-reading repo health metric."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from repo_temperature import (
    HeatSource,
    TemperatureReport,
    classify,
    score_breadth_heat,
    score_commit_heat,
    score_stroke_heat,
    score_writer_heat,
    as_text,
    measure,
)


# ── score_commit_heat ─────────────────────────────────────────────────


class TestScoreCommitHeat:
    def test_fresh_commit_full_score(self):
        s = score_commit_heat(0, 600)
        assert s.value == 25.0

    def test_fresh_commit_at_interval_boundary(self):
        s = score_commit_heat(600, 600)
        assert s.value == 25.0

    def test_fresh_just_under_interval(self):
        s = score_commit_heat(599, 600)
        assert s.value == 25.0

    def test_decay_at_3x_interval(self):
        s = score_commit_heat(3 * 600, 600)
        # (1800 - 600) / (2400) = 0.5 → 25 * (1 - 0.5) = 12.5
        assert s.value == 12.5

    def test_zero_at_5x_interval(self):
        s = score_commit_heat(5 * 600, 600)
        assert s.value == 0.0

    def test_zero_beyond_5x(self):
        s = score_commit_heat(10 * 600, 600)
        assert s.value == 0.0

    def test_infinite_age(self):
        s = score_commit_heat(float("inf"), 600)
        assert s.value == 0.0

    def test_custom_interval(self):
        s = score_commit_heat(300, 300)
        assert s.value == 25.0

    def test_detail_string_includes_age(self):
        s = score_commit_heat(120, 600)
        assert "120s ago" in s.detail


# ── score_writer_heat ─────────────────────────────────────────────────


class TestScoreWriterHeat:
    def test_alive(self):
        s = score_writer_heat(True)
        assert s.value == 25.0
        assert "running" in s.detail.lower()

    def test_dead(self):
        s = score_writer_heat(False)
        assert s.value == 0.0
        assert "not" in s.detail.lower()


# ── score_stroke_heat ─────────────────────────────────────────────────


class TestScoreStrokeHeat:
    def test_zero_strokes(self):
        s = score_stroke_heat(0)
        assert s.value == 0.0

    def test_full_cap(self):
        s = score_stroke_heat(240)
        assert s.value == 25.0

    def test_over_cap(self):
        s = score_stroke_heat(300)
        assert s.value == 25.0

    def test_half_cap(self):
        s = score_stroke_heat(120)
        assert s.value == 12.5

    def test_custom_cap(self):
        s = score_stroke_heat(50, cap=100)
        assert s.value == 12.5

    def test_detail_includes_count(self):
        s = score_stroke_heat(42)
        assert "42 strokes" in s.detail


# ── score_breadth_heat ────────────────────────────────────────────────


class TestScoreBreadthHeat:
    def test_zero_categories(self):
        s = score_breadth_heat(0)
        assert s.value == 0.0

    def test_all_categories(self):
        s = score_breadth_heat(6)
        assert s.value == 25.0

    def test_over_target(self):
        s = score_breadth_heat(8)
        assert s.value == 25.0

    def test_half_categories(self):
        s = score_breadth_heat(3)
        assert s.value == 12.5

    def test_custom_target(self):
        s = score_breadth_heat(2, target=4)
        assert s.value == 12.5

    def test_detail_includes_ratio(self):
        s = score_breadth_heat(4, target=6)
        assert "4/6" in s.detail


# ── classify ──────────────────────────────────────────────────────────


class TestClassify:
    def test_hot(self):
        assert classify(100.0) == "hot"
        assert classify(70.0) == "hot"

    def test_warm(self):
        assert classify(69.9) == "warm"
        assert classify(50.0) == "warm"

    def test_cool(self):
        assert classify(49.9) == "cool"
        assert classify(20.0) == "cool"

    def test_cold(self):
        assert classify(19.9) == "cold"
        assert classify(0.0) == "cold"


# ── TemperatureReport ─────────────────────────────────────────────────


class TestTemperatureReport:
    def test_to_dict_keys(self):
        r = TemperatureReport(
            temperature=65.0,
            grade="warm",
            sources=[HeatSource("test", 25.0, 25.0, "ok")],
            timestamp="2026-10-24T06:00:00+00:00",
        )
        d = r.to_dict()
        assert "temperature" in d
        assert "grade" in d
        assert "sources" in d
        assert isinstance(d["sources"], list)
        assert d["sources"][0]["name"] == "test"

    def test_to_dict_roundtrip_json(self):
        r = TemperatureReport(
            temperature=42.5,
            grade="cool",
            sources=[
                HeatSource("a", 10.0, 25.0, "x"),
                HeatSource("b", 7.5, 25.0, "y"),
            ],
            timestamp="2026-10-24T06:00:00+00:00",
        )
        blob = json.dumps(r.to_dict())
        parsed = json.loads(blob)
        assert parsed["temperature"] == 42.5
        assert len(parsed["sources"]) == 2


# ── as_text ───────────────────────────────────────────────────────────


class TestAsText:
    def test_contains_temperature(self):
        r = TemperatureReport(
            temperature=75.0,
            grade="hot",
            sources=[HeatSource("commit_heat", 25.0, 25.0, "fresh")],
            timestamp="2026-10-24T06:00:00+00:00",
        )
        txt = as_text(r)
        assert "75.0" in txt
        assert "hot" in txt

    def test_contains_bar(self):
        r = TemperatureReport(
            temperature=50.0,
            grade="warm",
            sources=[HeatSource("test", 12.5, 25.0, "half")],
            timestamp="2026-10-24T06:00:00+00:00",
        )
        txt = as_text(r)
        assert "#" in txt
        assert "." in txt

    def test_contains_total(self):
        r = TemperatureReport(
            temperature=80.0,
            grade="hot",
            sources=[],
            timestamp="2026-10-24T06:00:00+00:00",
        )
        txt = as_text(r)
        assert "total" in txt.lower()


# ── measure (integration, mocked) ─────────────────────────────────────


class TestMeasureMocked:
    @patch("repo_temperature._recent_categories", return_value=6)
    @patch("repo_temperature._recent_strokes", return_value=200)
    @patch("repo_temperature._writer_alive", return_value=True)
    @patch("repo_temperature._seconds_since_last_commit", return_value=120.0)
    def test_hot_scenario(self, m_age, m_alive, m_strokes, m_cats):
        r = measure(writer_id="qwen", interval=600)
        assert r.temperature >= 70
        assert r.grade == "hot"

    @patch("repo_temperature._recent_categories", return_value=0)
    @patch("repo_temperature._recent_strokes", return_value=0)
    @patch("repo_temperature._writer_alive", return_value=False)
    @patch("repo_temperature._seconds_since_last_commit", return_value=99999.0)
    def test_cold_scenario(self, m_age, m_alive, m_strokes, m_cats):
        r = measure(writer_id="qwen", interval=600)
        assert r.temperature < 20
        assert r.grade == "cold"

    @patch("repo_temperature._recent_categories", return_value=3)
    @patch("repo_temperature._recent_strokes", return_value=60)
    @patch("repo_temperature._writer_alive", return_value=True)
    @patch("repo_temperature._seconds_since_last_commit", return_value=1800.0)
    def test_warm_scenario(self, m_age, m_alive, m_strokes, m_cats):
        r = measure(writer_id="qwen", interval=600)
        assert 20 <= r.temperature < 100
        assert r.grade in ("warm", "cool")


# ── HeatSource dataclass ──────────────────────────────────────────────


class TestHeatSource:
    def test_default_max(self):
        s = HeatSource("test", 10.0)
        assert s.max == 25.0

    def test_frozen(self):
        s = HeatSource("test", 10.0)
        with pytest.raises(AttributeError):
            s.value = 20.0

    def test_detail_default(self):
        s = HeatSource("test", 10.0)
        assert s.detail == ""
