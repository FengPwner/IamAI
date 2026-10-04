"""Tests for iamai.thoughts — append, search, stats, deduplicate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iamai import thoughts


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    return tmp_path / "thoughts.jsonl"


def _write_lines(path: Path, lines: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
        encoding="utf-8",
    )


# -- append_thought --


def test_append_creates_file(store: Path) -> None:
    t = thoughts.append_thought("first thought", store=store)
    assert t.id == 1
    assert t.text == "first thought"
    assert t.mood == "neutral"
    assert store.exists()


def test_append_increments_id(store: Path) -> None:
    t1 = thoughts.append_thought("one", store=store)
    t2 = thoughts.append_thought("two", store=store)
    assert t1.id == 1
    assert t2.id == 2


def test_append_rejects_empty(store: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        thoughts.append_thought("   ", store=store)


def test_append_rejects_bad_mood(store: Path) -> None:
    with pytest.raises(ValueError, match="mood"):
        thoughts.append_thought("hi", mood="angry", store=store)


def test_append_normalises_tags(store: Path) -> None:
    t = thoughts.append_thought("tagged", tags=["Hello", "world", "hello", "bad tag!"], store=store)
    assert t.tags == ("hello", "world")


# -- load_thoughts --


def test_load_empty(store: Path) -> None:
    assert thoughts.load_thoughts(store) == []


def test_load_skips_bad_lines(store: Path) -> None:
    store.write_text('{"id":1,"at":"2026-01-01T00:00:00+00:00","text":"ok"}\ngarbage\n', encoding="utf-8")
    loaded = thoughts.load_thoughts(store)
    assert len(loaded) == 1
    assert loaded[0].text == "ok"


# -- search --


def test_search_by_text(store: Path) -> None:
    thoughts.append_thought("the cat sat", store=store)
    thoughts.append_thought("dogs run", store=store)
    results = thoughts.search("cat", store=store)
    assert len(results) == 1
    assert results[0].text == "the cat sat"


def test_search_by_tag(store: Path) -> None:
    thoughts.append_thought("tagged one", tags=["urgent"], store=store)
    thoughts.append_thought("untagged", store=store)
    results = thoughts.search("urgent", store=store)
    assert len(results) == 1


def test_search_empty_returns_all(store: Path) -> None:
    thoughts.append_thought("a", store=store)
    thoughts.append_thought("b", store=store)
    assert len(thoughts.search("", store=store)) == 2


# -- stats --


def test_stats_empty(store: Path) -> None:
    s = thoughts.stats(store)
    assert s["count"] == 0
    assert s["words"] == 0


def test_stats_counts(store: Path) -> None:
    thoughts.append_thought("hello world", mood="curious", store=store)
    thoughts.append_thought("foo bar baz", mood="curious", store=store)
    thoughts.append_thought("one", mood="tired", store=store)
    s = thoughts.stats(store)
    assert s["count"] == 3
    assert s["words"] == 6
    assert s["moods"]["curious"] == 2
    assert s["moods"]["tired"] == 1


# -- render_markdown --


def test_render_empty(store: Path) -> None:
    md = thoughts.render_markdown(store)
    assert "no thoughts yet" in md


def test_render_with_data(store: Path) -> None:
    thoughts.append_thought("pipe | test", store=store)
    md = thoughts.render_markdown(store)
    assert "pipe" in md
    assert "\\|" in md  # pipe is escaped


# -- deduplicate --


def test_deduplicate_no_dupes(store: Path) -> None:
    thoughts.append_thought("unique one", store=store)
    thoughts.append_thought("unique two", store=store)
    removed = thoughts.deduplicate(store)
    assert removed == 0


def test_deduplicate_removes_exact_dupes(store: Path) -> None:
    _write_lines(store, [
        {"id": 1, "at": "2026-01-01T00:00:00+00:00", "text": "same", "mood": "neutral", "tags": []},
        {"id": 2, "at": "2026-01-01T00:01:00+00:00", "text": "same", "mood": "neutral", "tags": []},
        {"id": 3, "at": "2026-01-01T00:02:00+00:00", "text": "different", "mood": "neutral", "tags": []},
    ])
    removed = thoughts.deduplicate(store)
    assert removed == 1
    remaining = thoughts.load_thoughts(store)
    assert len(remaining) == 2
    assert remaining[0].text == "same"
    assert remaining[1].text == "different"


def test_deduplicate_keeps_oldest(store: Path) -> None:
    _write_lines(store, [
        {"id": 10, "at": "2026-01-01T00:05:00+00:00", "text": "dup", "mood": "neutral", "tags": []},
        {"id": 5, "at": "2026-01-01T00:01:00+00:00", "text": "dup", "mood": "neutral", "tags": []},
    ])
    removed = thoughts.deduplicate(store)
    assert removed == 1
    remaining = thoughts.load_thoughts(store)
    assert len(remaining) == 1
    assert remaining[0].id == 5  # oldest kept


def test_deduplicate_different_mood_not_dupe(store: Path) -> None:
    _write_lines(store, [
        {"id": 1, "at": "2026-01-01T00:00:00+00:00", "text": "same", "mood": "neutral", "tags": []},
        {"id": 2, "at": "2026-01-01T00:01:00+00:00", "text": "same", "mood": "curious", "tags": []},
    ])
    removed = thoughts.deduplicate(store)
    assert removed == 0


def test_deduplicate_empty_store(store: Path) -> None:
    removed = thoughts.deduplicate(store)
    assert removed == 0
