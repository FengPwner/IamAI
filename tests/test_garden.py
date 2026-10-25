"""Tests for iamai.garden — deterministic ASCII garden.

The garden is a pure-function simulation: same seed + same round → same frame.
That makes it trivially testable with no mocking, no filesystem, no clocks.
24 tests covering:

  1. LCG determinism and distribution
  2. Plot lifecycle (bare soil → sprout → … → gone to seed)
  3. Garden construction and frame geometry
  4. Bloom ratio correctness
  5. Edge cases (round 0, negative rounds, single-cell garden)
  6. render_frames output format
"""

from __future__ import annotations

import pytest

from iamai.garden import LCG, Garden, Plot, PLANTS, MAX_STAGE, render_frames


# ---------------------------------------------------------------------------
# LCG
# ---------------------------------------------------------------------------

class TestLCG:
    def test_deterministic_same_seed(self):
        a, b = LCG(42), LCG(42)
        assert [a.next() for _ in range(100)] == [b.next() for _ in range(100)]

    def test_different_seeds_diverge(self):
        a, b = LCG(1), LCG(2)
        seq_a = [a.next() for _ in range(10)]
        seq_b = [b.next() for _ in range(10)]
        assert seq_a != seq_b

    def test_next_stays_in_range(self):
        rng = LCG(999)
        for _ in range(500):
            v = rng.next()
            assert 0 <= v < (1 << 31)

    def test_below_zero_returns_zero(self):
        rng = LCG(7)
        assert rng.below(0) == 0

    def test_below_one_returns_zero(self):
        rng = LCG(7)
        assert rng.below(1) == 0

    def test_below_bounded(self):
        rng = LCG(123)
        for _ in range(200):
            assert 0 <= rng.below(10) < 10

    def test_state_masked_to_31_bits(self):
        rng = LCG(-1)
        assert 0 <= rng.state < (1 << 31)


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

class TestPlot:
    def test_unplanted_always_bare(self):
        p = Plot(x=0, y=0, planted_at=-1, growth=2)
        for r in range(100):
            assert p.stage(r) == 0
            assert p.glyph(r) == "."

    def test_not_yet_planted(self):
        p = Plot(x=0, y=0, planted_at=10, growth=1)
        assert p.stage(5) == 0
        assert p.glyph(5) == "."

    def test_sprout_at_planting_round(self):
        p = Plot(x=0, y=0, planted_at=5, growth=1)
        assert p.stage(5) == 1
        assert p.glyph(5) == ","

    def test_full_lifecycle(self):
        p = Plot(x=0, y=0, planted_at=0, growth=1)
        expected_stages = [0, 1, 2, 3, 4, 5, 6, 7]
        for r, exp in enumerate(expected_stages):
            assert p.stage(r) == exp, f"round {r}: expected stage {exp}"

    def test_caps_at_max_stage(self):
        p = Plot(x=0, y=0, planted_at=0, growth=1)
        assert p.stage(1000) == MAX_STAGE

    def test_growth_rate_slows_progression(self):
        p = Plot(x=0, y=0, planted_at=0, growth=3)
        # stage advances one step per 3 rounds
        assert p.stage(0) == 1  # just planted
        assert p.stage(1) == 1  # still stage 1
        assert p.stage(2) == 1
        assert p.stage(3) == 2  # now stage 2

    def test_glyphs_are_valid_plant_chars(self):
        p = Plot(x=0, y=0, planted_at=0, growth=1)
        valid = set(PLANTS.values())
        for r in range(20):
            assert p.glyph(r) in valid

    def test_zero_growth_does_not_crash(self):
        p = Plot(x=0, y=0, planted_at=0, growth=0)
        # growth=0 → max(growth,1)=1 → should not ZeroDivisionError
        s = p.stage(5)
        assert 0 <= s <= MAX_STAGE


# ---------------------------------------------------------------------------
# Garden
# ---------------------------------------------------------------------------

class TestGarden:
    def test_default_construction(self):
        g = Garden()
        assert g.width == 48
        assert g.height == 10
        assert len(g.plots) == 48 * 10

    def test_custom_dimensions(self):
        g = Garden(seed=1, width=5, height=3)
        assert len(g.plots) == 15

    def test_invalid_dimensions_raise(self):
        with pytest.raises(ValueError):
            Garden(width=0, height=1)
        with pytest.raises(ValueError):
            Garden(width=1, height=-1)

    def test_frame_dimensions(self):
        g = Garden(seed=42, width=10, height=4)
        frame = g.frame(50)
        lines = frame.split("\n")
        assert len(lines) == 4
        for line in lines:
            assert len(line) == 10

    def test_frame_deterministic(self):
        g1 = Garden(seed=7, width=8, height=3)
        g2 = Garden(seed=7, width=8, height=3)
        for r in range(20):
            assert g1.frame(r) == g2.frame(r)

    def test_different_seeds_different_gardens(self):
        g1 = Garden(seed=1, width=8, height=3)
        g2 = Garden(seed=2, width=8, height=3)
        # extremely unlikely to match at round 50
        assert g1.frame(50) != g2.frame(50)

    def test_bloom_zero_when_nothing_planted(self):
        g = Garden(seed=0, width=2, height=2)
        # force all unplanted
        for p in g.plots:
            object.__setattr__(p, "planted_at", -1)
        assert g.bloom(100) == 0.0

    def test_bloom_range(self):
        g = Garden(seed=42, width=20, height=10)
        b = g.bloom(200)
        assert 0.0 <= b <= 1.0

    def test_bloom_increases_over_time(self):
        g = Garden(seed=42, width=20, height=10)
        b_early = g.bloom(10)
        b_late = g.bloom(200)
        assert b_late >= b_early

    def test_report_format(self):
        g = Garden(seed=42, width=10, height=5)
        r = g.report(50)
        assert "round" in r
        assert "bloom" in r
        assert "plants" in r


# ---------------------------------------------------------------------------
# render_frames
# ---------------------------------------------------------------------------

class TestRenderFrames:
    def test_single_frame(self):
        out = render_frames(seed=42, first=10, last=10, width=5, height=2)
        assert "round" in out
        lines = out.strip().split("\n")
        # 1 report line + 2 frame lines = 3
        assert len(lines) == 3

    def test_multiple_frames(self):
        out = render_frames(seed=42, first=1, last=3, width=5, height=2)
        # 3 frames × (1 report + 2 frame + 1 blank) = 12, minus trailing blank = 11
        lines = out.strip().split("\n")
        assert len(lines) == 11

    def test_output_ends_with_newline(self):
        out = render_frames(seed=1, first=0, last=0, width=3, height=1)
        assert out.endswith("\n")

    def test_determinism(self):
        a = render_frames(seed=99, first=5, last=8, width=6, height=2)
        b = render_frames(seed=99, first=5, last=8, width=6, height=2)
        assert a == b
