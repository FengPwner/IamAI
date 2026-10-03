"""Tests for the bug that put a "quiet batch" label on 38 strokes of work.

Two processes share one directory and used to share one state file. The writer
rewrote that file on every stroke, so the committer's in-memory copy went stale and
its window tally came out empty -- it committed real work under a false "nothing
new" subject. Fixes encoded here:

    * commit bookkeeping lives in its own file, so neither process clobbers the other
    * the window tally is a pure function over history, testable without processes
    * a subject must never claim silence while there are staged changes
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iamai import batch, writer


# --- separation of ownership ---------------------------------------------


def test_committer_does_not_clobber_writer_counters(tmp_path: Path):
    writer_state = tmp_path / "data" / "writer_state.json"
    commit_state = tmp_path / "data" / "commit_state.json"

    w = writer.States(path=writer_state, commit_path=commit_state)
    c = writer.States(path=writer_state, commit_path=commit_state)

    w.record(kind="thought", path="data/strokes.jsonl")
    c.mark_commit("2026-10-03T03:39:07+00:00")
    w.record(kind="devlog", path="docs/DEVLOG.md")

    reloaded = writer.States(path=writer_state, commit_path=commit_state)
    assert reloaded.tally() == {"thought": 1, "devlog": 1}, "writer counters survived"
    assert reloaded.last_commit == "2026-10-03T03:39:07+00:00", "commit bookkeeping survived"
    assert commit_state.exists(), "commit bookkeeping has its own file"


def test_mark_commit_does_not_reset_the_history(tmp_path: Path):
    state = writer.States(
        path=tmp_path / "w.json", commit_path=tmp_path / "c.json"
    )
    state.record(kind="garden", path="docs/GARDEN.md")
    state.mark_commit("2026-10-03T03:39:07+00:00")
    assert [h["kind"] for h in state.data["history"]] == ["garden"]


# --- window tally: pure, over history ------------------------------------


HISTORY = [
    {"seq": 1, "at": "2026-10-03T03:28:00+00:00", "kind": "thought", "path": "p"},
    {"seq": 2, "at": "2026-10-03T03:29:00+00:00", "kind": "garden", "path": "p"},
    {"seq": 3, "at": "2026-10-03T03:30:00+00:00", "kind": "garden", "path": "p"},
    {"seq": 4, "at": "2026-10-03T03:31:00+00:00", "kind": "note", "path": "p"},
]


def test_window_tally_counts_only_the_open_window():
    assert batch.window_tally(HISTORY, "2026-10-03T03:28:30+00:00") == {
        "garden": 2,
        "note": 1,
    }


def test_window_tally_with_no_lower_bound_counts_everything():
    assert batch.window_tally(HISTORY, None) == {"thought": 1, "garden": 2, "note": 1}


def test_window_tally_ignores_malformed_entries():
    messy = HISTORY + [{"kind": "thought"}, {"at": "nope"}, {}]
    assert batch.window_tally(messy, None) == {"thought": 1, "garden": 2, "note": 1}


def test_window_tally_of_nothing_is_empty_not_none():
    assert batch.window_tally([], None) == {}


# --- a subject must not lie about silence ---------------------------------


def test_silence_is_only_claimed_when_there_is_nothing_staged():
    assert "quiet" in batch.subject({}, window_seconds=600, pending=0)


def test_work_is_claimed_even_when_the_writer_stayed_unrecorded():
    subject = batch.subject({}, window_seconds=600, pending=4)
    assert "quiet" not in subject
    assert "unrecorded" in subject or "4" in subject


def test_a_normal_window_reads_as_counts_not_apologies():
    subject = batch.subject({"thought": 11, "garden": 4}, window_seconds=600, pending=2)
    assert subject.startswith("batch: ")
    assert "thought x11" in subject
    assert "unrecorded" not in subject


def test_pending_defaults_to_work_being_present():
    assert "quiet" not in batch.subject({}, window_seconds=600)
