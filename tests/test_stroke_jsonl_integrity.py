"""Tests for tools/stroke_jsonl_integrity.py — structural validation of strokes.jsonl."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stroke_jsonl_integrity import validate, REQUIRED_FIELDS


def _make_lines(records: list[dict]) -> list[str]:
    return [json.dumps(r) for r in records]


def test_clean_input():
    recs = [
        {"seq": 1, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "hello"},
        {"seq": 2, "at": "2026-01-01T00:00:15+00:00", "kind": "note", "text": "world"},
        {"seq": 3, "at": "2026-01-01T00:00:30+00:00", "kind": "devlog", "text": "day one"},
    ]
    report = validate(_make_lines(recs))
    assert report["valid"] == 3
    assert report["errors"] == 0
    assert report["warnings"] == 0


def test_bad_json():
    lines = ['{"seq":1,"at":"2026-01-01T00:00:00+00:00","kind":"thought","text":"ok"}', "not json at all"]
    report = validate(lines)
    assert report["errors"] == 1
    assert report["error_details"][0]["issue"] == "bad_json"


def test_missing_fields():
    recs = [{"seq": 1, "at": "2026-01-01T00:00:00+00:00"}]  # missing kind, text
    report = validate(_make_lines(recs))
    assert report["errors"] == 1
    err = report["error_details"][0]
    assert err["issue"] == "missing_fields"
    assert "kind" in err["detail"]
    assert "text" in err["detail"]


def test_duplicate_seq():
    recs = [
        {"seq": 1, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "a"},
        {"seq": 1, "at": "2026-01-01T00:00:15+00:00", "kind": "note", "text": "b"},
    ]
    report = validate(_make_lines(recs))
    assert any(e["issue"] == "duplicate_seq" for e in report["error_details"])


def test_seq_regression():
    recs = [
        {"seq": 5, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "a"},
        {"seq": 3, "at": "2026-01-01T00:00:15+00:00", "kind": "thought", "text": "b"},
    ]
    report = validate(_make_lines(recs))
    assert any(e["issue"] == "seq_regression" for e in report["error_details"])


def test_timestamp_regression_beyond_tolerance():
    recs = [
        {"seq": 1, "at": "2026-01-01T01:00:00+00:00", "kind": "thought", "text": "late"},
        {"seq": 2, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "early"},
    ]
    report = validate(_make_lines(recs))
    assert any(e["issue"] == "timestamp_regression" for e in report["error_details"])


def test_timestamp_drift_within_tolerance():
    # 2 minutes drift — within 5 minute tolerance
    recs = [
        {"seq": 1, "at": "2026-01-01T00:10:00+00:00", "kind": "thought", "text": "a"},
        {"seq": 2, "at": "2026-01-01T00:08:00+00:00", "kind": "note", "text": "b"},
    ]
    report = validate(_make_lines(recs))
    assert report["errors"] == 0
    assert report["warnings"] == 1
    assert report["warning_details"][0]["issue"] == "timestamp_drift"


def test_duplicate_pair():
    recs = [
        {"seq": 1, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "a"},
        {"seq": 2, "at": "2026-01-01T00:00:15+00:00", "kind": "thought", "text": "b"},
        {"seq": 1, "at": "2026-01-01T00:00:30+00:00", "kind": "thought", "text": "c"},
    ]
    report = validate(_make_lines(recs))
    assert any(e["issue"] == "duplicate_pair" for e in report["error_details"])


def test_empty_lines_skipped():
    lines = [
        '{"seq":1,"at":"2026-01-01T00:00:00+00:00","kind":"thought","text":"ok"}',
        "",
        '{"seq":2,"at":"2026-01-01T00:00:15+00:00","kind":"note","text":"fine"}',
    ]
    report = validate(lines)
    assert report["valid"] == 2
    assert report["errors"] == 0


def test_offset_tracking():
    lines = ['{"seq":10,"at":"2026-01-01T00:00:00+00:00","kind":"thought","text":"ok"}']
    report = validate(lines, offset=99)
    # line numbers should start at offset+1
    assert report["valid"] == 1
    assert report["errors"] == 0


def test_bad_timestamp():
    recs = [{"seq": 1, "at": "not-a-date", "kind": "thought", "text": "broken"}]
    report = validate(_make_lines(recs))
    assert any(e["issue"] == "bad_timestamp" for e in report["error_details"])
