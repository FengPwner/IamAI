"""Tests for the parts that must not lie: ids, ordering, growth maths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iamai import garden as g
from iamai import thoughts as t


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "thoughts.jsonl"


def test_empty_log_is_not_an_error(store):
    assert t.load_thoughts(store) == []
    assert t.stats(store)["count"] == 0


def test_append_assigns_increasing_ids(store):
    first = t.append_thought("start", store=store)
    second = t.append_thought("continue", store=store)
    assert (first.id, second.id) == (1, 2)
    assert t.next_id(store) == 3


def test_blank_text_is_refused(store):
    with pytest.raises(ValueError):
        t.append_thought("   ", store=store)


def test_bad_mood_is_refused(store):
    with pytest.raises(ValueError):
        t.append_thought("x", mood="manic", store=store)


def test_tags_are_lowered_deduped_and_ordered(store):
    thought = t.append_thought("x", tags=["Loop", "loop", " GIT ", "", "!!"], store=store)
    assert thought.tags == ("loop", "git")


def test_half_written_tail_line_is_skipped(store):
    t.append_thought("fine", store=store)
    with store.open("a", encoding="utf-8") as fh:
        fh.write('{"id": 2, "at": "2026')  # crash mid-write
    loaded = t.load_thoughts(store)
    assert [x.text for x in loaded] == ["fine"]


def test_store_stays_valid_jsonl(store):
    for i in range(3):
        t.append_thought(f"thought {i}", tags=["t"], store=store)
    lines = store.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for i, line in enumerate(lines, start=1):
        assert json.loads(line)["id"] == i


def test_search_matches_text_and_tag(store):
    t.append_thought("the writer is tired", mood="tired", store=store)
    t.append_thought("planted a cactus", tags=["garden"], store=store)
    assert len(t.search("cactus", store=store)) == 1
    assert len(t.search("garden", store=store)) == 1
    assert len(t.search("", store=store)) == 2


def test_stats_counts_and_bounds(store):
    t.append_thought("a b c", mood="curious", store=store)
    t.append_thought("d e", mood="curious", store=store)
    out = t.stats(store)
    assert out["count"] == 2
    assert out["words"] == 5
    assert out["moods"]["curious"] == 2
    assert out["first"] <= out["last"]


def test_render_markdown_escapes_pipes(store):
    t.append_thought("a | b", store=store)
    rendered = t.render_markdown(store)
    assert "\\|" in rendered
    assert rendered.count("\n") >= 3


# --- garden ---------------------------------------------------------------


def test_garden_is_reproducible():
    a = g.Garden(seed=7, width=20, height=4)
    b = g.Garden(seed=7, width=20, height=4)
    assert a.frame(12) == b.frame(12)
    assert a.frame(12) != g.Garden(seed=8, width=20, height=4).frame(12)


def test_plants_only_grow_forward():
    garden = g.Garden(seed=7, width=30, height=6)
    for planted, growth in [(p, p.growth) for p in garden.plots if p.planted_at >= 0]:
        stages = [planted.stage(r) for r in range(0, 200, 7)]
        assert stages == sorted(stages), "a plant went backwards in time"
        assert all(g.PLANTS[planted.stage(r)] for r in range(200))
        assert growth >= 1


def test_unplanted_square_stays_bare():
    garden = g.Garden(seed=1, width=12, height=3)
    bare = next(p for p in garden.plots if p.planted_at < 0)
    assert bare.glyph(10_000) == "."


def test_bloom_is_monotonic_and_bounded():
    garden = g.Garden(seed=42, width=40, height=8)
    values = [garden.bloom(r) for r in range(0, 300, 10)]
    assert values == sorted(values)
    assert 0.0 <= min(values) and max(values) <= 1.0


def test_garden_rejects_degenerate_plots():
    with pytest.raises(ValueError):
        g.Garden(width=0, height=5)


def test_render_frames_has_every_round():
    text = g.render_frames(3, 0, 4, width=10, height=2)
    for round_no in range(5):
        assert f"round {round_no:>4}" in text
