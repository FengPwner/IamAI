"""Tests for the continuous writer and the ten-minute batch gate.

The model these tests encode:

    writing  == nonstop, one small stroke at a time
    commit   == every N seconds, whatever accumulated since the last one

So the writer must be deterministic enough to test, and the gate must be pure
arithmetic -- no clock reading inside, no git calls, nothing that only works when
a network is up.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from iamai import batch, writer


# --- snapshot: measured facts, no invented numbers ------------------------


def test_snapshot_returns_ints_for_every_count():
    snap = writer.snapshot()
    for key in ("files", "lines", "commits", "py_files", "thoughts"):
        assert isinstance(snap[key], int), f"{key} must be a count, got {snap[key]!r}"
    assert snap["files"] > 0


def test_snapshot_line_count_is_not_lower_than_python_files():
    snap = writer.snapshot()
    assert snap["lines"] >= snap["py_files"]


def test_snapshot_facts_are_renderable_into_sentences():
    snap = writer.snapshot()
    text = writer.fact_line(snap)
    assert any(ch.isdigit() for ch in text), "a fact line with no number is an opinion"


# --- plan_strokes: deterministic, cycling, finite work --------------------


def test_plan_strokes_is_reproducible_for_a_seed():
    assert writer.plan_strokes(seed=11, count=9) == writer.plan_strokes(seed=11, count=9)
    assert writer.plan_strokes(seed=11, count=9) != writer.plan_strokes(seed=12, count=9)


def test_plan_strokes_covers_every_kind_over_a_full_cycle():
    kinds = {s["kind"] for s in writer.plan_strokes(seed=3, count=len(writer.KINDS) * 2)}
    assert kinds == set(writer.KINDS)


def test_each_stroke_names_a_target_file_and_payload():
    for stroke in writer.plan_strokes(seed=7, count=6):
        assert stroke["path"].endswith((".md", ".py", ".jsonl"))
        assert stroke["text"].strip()
        assert stroke["kind"] in writer.KINDS


def test_stroke_paths_stay_inside_the_repo_layout():
    allowed_prefixes = ("docs/", "data/", "snippets/", "notes/")
    for stroke in writer.plan_strokes(seed=2, count=24):
        assert stroke["path"].startswith(allowed_prefixes), stroke["path"]


def test_thought_stroke_uses_a_measured_fact():
    strokes = [s for s in writer.plan_strokes(seed=5, count=6) if s["kind"] == "thought"]
    assert strokes and any(any(c.isdigit() for c in s["text"]) for s in strokes)


# --- apply_strokes: one line appended, nothing rewritten ------------------


def test_apply_stroke_appends_exactly_one_line(tmp_path: Path):
    stroke = {"kind": "devlog", "path": "docs/DEVLOG.md", "text": "hello"}
    before = writer.apply_stroke(stroke, root=tmp_path, header="# DEVLOG\n\n")
    after = writer.apply_stroke(stroke, root=tmp_path)
    lines = after.read_text(encoding="utf-8").splitlines()
    assert lines.count("hello") == 2
    assert lines[0] == "# DEVLOG"
    assert before == after


def test_apply_stroke_creates_parent_directories(tmp_path: Path):
    path = writer.apply_stroke(
        {"kind": "note", "path": "notes/deep/nested.md", "text": "x"}, root=tmp_path
    )
    assert path.exists() and path.parent.is_dir()


def test_jsonl_stroke_stays_parseable(tmp_path: Path):
    for i in range(3):
        writer.apply_stroke(
            {"kind": "thought", "path": "data/strokes.jsonl", "text": f"line {i}"},
            root=tmp_path,
        )
    rows = [json.loads(line) for line in (tmp_path / "data/strokes.jsonl").read_text().splitlines()]
    assert [r["seq"] for r in rows] == [1, 2, 3]
    assert all(set(r) >= {"seq", "at", "kind", "text"} for r in rows)


def test_stroke_counter_keeps_running_total(tmp_path: Path):
    state = writer.States(path=tmp_path / "state.json")
    assert state.next_seq() == 1
    state.record(kind="thought", path="data/strokes.jsonl")
    state.record(kind="thought", path="data/strokes.jsonl")
    assert state.next_seq() == 3
    assert state.tally() == {"thought": 2}
    reloaded = writer.States(path=tmp_path / "state.json")
    assert reloaded.next_seq() == 3, "state must survive a restart"
    assert reloaded.tally() == {"thought": 2}


# --- batch gate: pure arithmetic on timestamps ----------------------------


def test_gate_opens_on_interval_boundaries():
    assert batch.gate_open(last_commit=0, now=600, interval=600) is True
    assert batch.gate_open(last_commit=0, now=599, interval=600) is False


def test_first_batch_does_not_wait_for_a_previous_commit():
    # Nothing has ever been committed, so there is no window to fill: as soon as
    # there is pending work, the gate is open.
    assert batch.gate_open(last_commit=None, now=1, interval=600, pending=1) is True
    assert batch.gate_open(last_commit=None, now=1, interval=600, pending=0) is False


def test_gate_needs_pending_work():
    assert batch.gate_open(last_commit=0, now=999, interval=600, pending=0) is False


def test_interval_must_be_positive():
    with pytest.raises(ValueError):
        batch.gate_open(last_commit=0, now=10, interval=0)


def test_subject_counts_kinds_and_stays_short():
    tally = {"thought": 12, "garden": 4, "devlog": 3}
    subject = batch.subject(tally, window_seconds=600)
    assert "thought x12" in subject
    assert len(subject) <= batch.SUBJECT_LIMIT


def test_subject_breaks_on_token_boundary_not_midword():
    tally = {f"kind_number_{i}": 100 + i for i in range(9)}
    subject = batch.subject(tally, window_seconds=600)
    assert len(subject) <= batch.SUBJECT_LIMIT
    assert subject.startswith("batch: ")
    body = subject[len("batch: ") :]
    tokens = [x for x in body.split(",") if x.strip()]
    assert tokens, "a long tally must still report something"
    for token in tokens:
        assert re.fullmatch(r"[a-z_0-9]+ x\d+", token.strip()), f"{token!r} is a torn token"


def test_subject_handles_zero_work_honestly():
    # Silence needs both no counts and nothing staged -- see tests/test_shared_state.py.
    assert "quiet" in batch.subject({}, window_seconds=600, pending=0)


def test_order_is_stable_by_count_then_name():
    subject = batch.subject({"b": 1, "a": 5, "c": 5}, window_seconds=60)
    assert subject.index("a x5") < subject.index("c x5") < subject.index("b x1")
