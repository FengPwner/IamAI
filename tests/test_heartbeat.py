"""Tests for iamai.heartbeat: can this repo tell whether it is still alive?

A continuously writing repository has one failure mode that matters more than a bug:
it stops and nobody notices, because a missing commit looks exactly like a quiet
minute. These tests pin down the arithmetic behind "the writer stalled".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from iamai import heartbeat


def iso(offset_seconds: float) -> str:
    return (datetime(2026, 10, 3, 3, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


@pytest.fixture
def history():
    return [
        {"seq": 1, "at": iso(0), "kind": "thought", "path": "data/strokes.jsonl"},
        {"seq": 2, "at": iso(15), "kind": "devlog", "path": "docs/DEVLOG.md"},
        {"seq": 3, "at": iso(30), "kind": "garden", "path": "docs/GARDEN.md"},
        {"seq": 4, "at": iso(200), "kind": "note", "path": "notes/limits.md"},
        {"seq": 5, "at": iso(215), "kind": "metrics", "path": "docs/METRICS.md"},
    ]


# --- basic window arithmetic ---------------------------------------------


def test_report_counts_the_open_window(history):
    report = heartbeat.report(history, since=iso(30), interval=600, now=iso(300))
    assert report["strokes"] == 2, "the window boundary is exclusive: 'at' must be after since"
    assert report["kinds"] == {"note": 1, "metrics": 1}


def test_report_with_no_lower_bound_counts_everything(history):
    report = heartbeat.report(history, since=None, interval=600, now=iso(300))
    assert report["strokes"] == 5
    assert len(report["paths"]) == 5


def test_empty_history_reports_zero_not_none():
    report = heartbeat.report([], since=None, interval=600, now=iso(0))
    assert report["strokes"] == 0
    assert report["first"] is None and report["last"] is None
    assert report["gap_seconds"] == 0.0


def test_report_ignores_malformed_rows(history):
    messy = history + [{"kind": "thought"}, {"at": "garbage"}, "not-a-dict", {}]
    report = heartbeat.report(messy, since=None, interval=600, now=iso(300))
    assert report["strokes"] == 5


# --- stall detection: the point of the whole module -----------------------


def test_longest_gap_is_measured_between_consecutive_strokes(history):
    report = heartbeat.report(history, since=None, interval=600, now=iso(300))
    assert report["max_gap_seconds"] == 170.0  # 30 -> 200


def test_current_gap_counts_silence_since_the_last_stroke(history):
    report = heartbeat.report(history, since=None, interval=600, now=iso(300))
    assert report["gap_seconds"] == 85.0


def test_a_writer_silent_for_over_two_intervals_is_flagged_stalled(history):
    # interval here is the *commit* window; stroke cadence is passed in explicitly.
    report = heartbeat.report(history, since=None, interval=600, now=iso(215 + 120), every=15)
    assert report["stalled"] is True


def test_a_writer_on_cadence_is_not_flagged(history):
    report = heartbeat.report(history, since=None, interval=600, now=iso(215 + 20), every=15)
    assert report["stalled"] is False


def test_stall_check_without_a_cadence_is_ambiguous_and_stays_false():
    report = heartbeat.report([], since=None, interval=600, now=iso(10_000), every=None)
    assert report["stalled"] is False


def test_no_history_at_all_is_only_stalled_once_the_run_started():
    report = heartbeat.report([], since=None, interval=600, now=iso(10_000), every=15)
    assert report["strokes"] == 0 and report["stalled"] is False


# --- rendering ------------------------------------------------------------


def test_markdown_line_is_one_line_and_contains_the_counts(history):
    report = heartbeat.report(history, since=iso(30), interval=600, now=iso(300))
    line = heartbeat.as_markdown(report)
    assert "\n" not in line.strip()
    assert "2 strokes" in line
    assert "gap" in line


def test_markdown_says_stalled_in_words(history):
    report = heartbeat.report(history, since=None, interval=600, now=iso(215 + 500), every=15)
    assert "STALL" in heartbeat.as_markdown(report)


def test_beat_returns_a_report_that_reads_cleanly(history, tmp_path, monkeypatch):
    monkeypatch.setattr(heartbeat, "load_history", lambda path=None, writer_id=None, root=None: history)
    beat = heartbeat.beat(interval=600, every=15)
    assert beat["strokes"] == 5
    assert isinstance(heartbeat.as_markdown(beat), str)


# --- the probe must read THIS writer's bookkeeping -----------------------


def test_beat_reads_the_namespaced_state_file(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone, timedelta

    data = tmp_path / "data"
    data.mkdir()
    # 时间戳必须相对"现在"，否则探针按真实时钟算出来的 gap 会把 fixture 判成停滞。
    now = datetime.now(timezone.utc)
    mine = {"seq": 3, "tally": {}, "history": [
        {"seq": 1, "at": (now - timedelta(seconds=10)).isoformat(), "kind": "thought", "path": "p"},
        {"seq": 2, "at": (now - timedelta(seconds=5)).isoformat(), "kind": "devlog", "path": "p"},
    ]}
    theirs = {"seq": 900, "tally": {}, "history": [
        {"seq": i, "at": (now - timedelta(days=9)).isoformat(), "kind": "dpoem", "path": "p"} for i in range(899)
    ]}
    (data / "writer_state.qwen.json").write_text(json.dumps(mine), encoding="utf-8")
    (data / "writer_state.doubao.json").write_text(json.dumps(theirs), encoding="utf-8")

    beat = heartbeat.beat(root=tmp_path, writer_id="qwen")
    assert beat["strokes"] == 2, "must count my strokes, not another writer's"
    assert beat["stalled"] is False
    assert beat["gap_seconds"] < 30
    assert beat["source"].endswith("writer_state.qwen.json") and beat["legacy_source"] is False

    other = heartbeat.beat(root=tmp_path, writer_id="doubao")
    assert other["strokes"] == 899 and other["stalled"] is True, "九年没落笔的写手就该被判停滞"


def test_beat_falls_back_to_the_legacy_shared_file(tmp_path, monkeypatch):
    import json
    data = tmp_path / "data"
    data.mkdir()
    legacy = {"seq": 2, "tally": {}, "history": [
        {"seq": 1, "at": datetime.now(timezone.utc).isoformat(), "kind": "note", "path": "p"}
    ]}
    (data / "writer_state.json").write_text(json.dumps(legacy), encoding="utf-8")
    beat = heartbeat.beat(root=tmp_path, writer_id="nobody-yet")
    assert beat["strokes"] == 1, "a repo predating namespacing still has to be readable"
    assert beat["legacy_source"] is True, "but it must say so out loud"
