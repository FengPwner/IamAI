"""Tests for iamai.roster: who is writing this repository right now?

With several agents looping on one repo, the first question is no longer "is my
writer alive" but "who else is moving, and how fast". The roster answers that from
the per-writer state files that are already on disk -- no network, no coordination
protocol, just bookkeeping read honestly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from iamai import roster


def iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds")


def state(seq: int, history: list[dict]) -> str:
    return json.dumps({"seq": seq, "tally": {}, "history": history})


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "writer_state.qwen.json").write_text(
        state(4, [
            {"seq": 2, "at": iso(40), "kind": "thought", "path": "p"},
            {"seq": 3, "at": iso(20), "kind": "devlog", "path": "p"},
            {"seq": 4, "at": iso(8), "kind": "garden", "path": "p"},
        ]),
        encoding="utf-8",
    )
    (d / "writer_state.doubao.json").write_text(
        state(900, [{"seq": i, "at": iso(9000), "kind": "dpoem", "path": "p"} for i in range(899)]),
        encoding="utf-8",
    )
    (d / "writer_state.json").write_text(state(7, []), encoding="utf-8")
    return d


# --- discovery ------------------------------------------------------------


def test_roster_lists_every_writer_with_a_state_file(data_dir):
    assert roster.names(data_dir) == ["doubao", "qwen"]


def test_the_pre_namespacing_shared_file_is_labelled_not_mixed_in(data_dir):
    found = roster.names(data_dir, include_legacy=True)
    assert "legacy" in found and "qwen" in found
    assert roster.names(data_dir) == ["doubao", "qwen"], "legacy is opt-in only"


def test_a_missing_data_directory_is_an_empty_roster(tmp_path):
    assert roster.names(tmp_path / "nope") == []


# --- per-writer health ----------------------------------------------------


def test_active_writer_is_alive_and_silent_one_is_not(data_dir):
    rows = {row["writer"]: row for row in roster.roster(data_dir, every=15)}
    assert rows["qwen"]["alive"] is True
    assert rows["qwen"]["strokes"] == 3
    assert rows["qwen"]["gap_seconds"] < 20
    assert rows["doubao"]["alive"] is False, "899 strokes and 2.5 hours of silence is a stalled writer"


def test_kinds_are_counted_per_writer(data_dir):
    rows = {row["writer"]: row for row in roster.roster(data_dir, every=15)}
    assert rows["qwen"]["kinds"] == {"garden": 1, "devlog": 1, "thought": 1}
    assert rows["doubao"]["kinds"] == {"dpoem": 899}


def test_last_write_is_reported_for_each_writer(data_dir):
    rows = {row["writer"]: row for row in roster.roster(data_dir, every=15)}
    assert rows["qwen"]["last"].endswith("+00:00")
    assert rows["doubao"]["last"] is not None


def test_tie_breaking_and_ordering_are_stable(data_dir):
    ids = [row["writer"] for row in roster.roster(data_dir, every=15)]
    assert ids == sorted(ids), "the roster must not reshuffle between calls"


def test_broken_state_files_are_skipped_not_fatal(data_dir):
    (data_dir / "writer_state.broken.json").write_text("{nope", encoding="utf-8")
    ids = [row["writer"] for row in roster.roster(data_dir, every=15)]
    assert "broken" not in ids and "qwen" in ids


# --- rendering ------------------------------------------------------------


def test_markdown_is_one_row_per_writer(data_dir):
    table = roster.as_markdown(roster.roster(data_dir, every=15))
    lines = [ln for ln in table.splitlines() if ln.strip()]
    assert len(lines) == 4, "header + separator + one row per writer (fixture has two)"
    assert "qwen" in table and "doubao" in table
    assert "alive" in table.lower()


def test_an_empty_roster_still_renders(tmp_path):
    table = roster.as_markdown(roster.roster(tmp_path / "data", every=15))
    assert "no writers" in table


def test_total_helpers_sum_across_writers(data_dir):
    rows = roster.roster(data_dir, every=15)
    assert roster.total_strokes(rows) == 902
    assert roster.alive_writers(rows) == ["qwen"]
