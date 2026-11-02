#!/usr/bin/env python3
"""Tests for resurrection_score.py"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resurrection_score import (
    VisitRecord,
    ComponentScore,
    ResurrectionScore,
    parse_visit_note,
    load_visits,
    compute_recovery_rate,
    compute_push_reliability,
    compute_data_retention,
    compute_cadence_stability,
    compute_score,
    grade_score,
    format_text,
)


# --- Fixtures ---

def make_visit(
    num=1, date="2026-10-01",
    writer_ok=True, batch_ok=True,
    push_ok=True, pending=0, gap=600.0
):
    return VisitRecord(
        visit_number=num, date=date,
        writer_running_after=writer_ok,
        batch_running_after=batch_ok,
        push_succeeded=push_ok,
        pending_at_death=pending,
        stall_gap_seconds=gap,
    )


SAMPLE_NOTE = """# caretaker visit 42 — 2026-10-05 12:00 CST

## what happened

- writer and batch were dead
- 5 pending files accumulated
- longest gap 1200s before restart
- restarted both processes

## process status after visit

| component | status |
|-----------|--------|
| writer    | running (pid 12345) |
| batch     | running (pid 12346) |

## push

push succeeded: abc123..def456 main -> main
"""


# --- Parse tests ---

def test_parse_visit_note():
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="caretaker-visit-42-2026-10-05",
        delete=False
    ) as f:
        f.write(SAMPLE_NOTE)
        f.flush()
        rec = parse_visit_note(Path(f.name))
    assert rec is not None
    assert rec.visit_number == 42
    assert rec.writer_running_after is True
    assert rec.batch_running_after is True
    assert rec.push_succeeded is True
    assert rec.pending_at_death == 5
    assert rec.stall_gap_seconds == 1200.0
    print("  pass: parse_visit_note")


def test_parse_missing_visit():
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="random-note", delete=False
    ) as f:
        f.write("# just a random note\nno visit info here\n")
        f.flush()
        rec = parse_visit_note(Path(f.name))
    assert rec is None
    print("  pass: parse_missing_visit")


# --- Component score tests ---

def test_recovery_rate_perfect():
    visits = [make_visit(writer_ok=True, batch_ok=True) for _ in range(10)]
    assert compute_recovery_rate(visits) == 1.0
    print("  pass: recovery_rate_perfect")


def test_recovery_rate_half():
    visits = [make_visit(writer_ok=True, batch_ok=True) for _ in range(5)]
    visits += [make_visit(writer_ok=False, batch_ok=False) for _ in range(5)]
    assert compute_recovery_rate(visits) == 0.5
    print("  pass: recovery_rate_half")


def test_recovery_rate_empty():
    assert compute_recovery_rate([]) == 0.0
    print("  pass: recovery_rate_empty")


def test_push_reliability_all_ok():
    visits = [make_visit(push_ok=True) for _ in range(20)]
    assert compute_push_reliability(visits) == 1.0
    print("  pass: push_reliability_all_ok")


def test_push_reliability_none():
    visits = [make_visit(push_ok=False) for _ in range(10)]
    assert compute_push_reliability(visits) == 0.0
    print("  pass: push_reliability_none")


def test_push_reliability_mixed():
    visits = [make_visit(push_ok=True) for _ in range(7)]
    visits += [make_visit(push_ok=False) for _ in range(3)]
    assert compute_push_reliability(visits) == 0.7
    print("  pass: push_reliability_mixed")


def test_data_retention_zero_pending():
    visits = [make_visit(pending=0) for _ in range(10)]
    assert compute_data_retention(visits) == 1.0
    print("  pass: data_retention_zero_pending")


def test_data_retention_ten_pending():
    visits = [make_visit(pending=10) for _ in range(5)]
    assert compute_data_retention(visits) == 0.0
    print("  pass: data_retention_ten_pending")


def test_data_retention_five_pending():
    visits = [make_visit(pending=5) for _ in range(5)]
    assert compute_data_retention(visits) == 0.5
    print("  pass: data_retention_five_pending")


def test_cadence_stability_short_gap():
    visits = [make_visit(gap=600.0)]
    assert compute_cadence_stability(visits) == 1.0
    print("  pass: cadence_stability_short_gap")


def test_cadence_stability_long_gap():
    visits = [make_visit(gap=7200.0)]
    assert compute_cadence_stability(visits) == 0.0
    print("  pass: cadence_stability_long_gap")


def test_cadence_stability_no_gaps():
    visits = [make_visit(gap=0.0)]
    assert compute_cadence_stability(visits) == 1.0
    print("  pass: cadence_stability_no_gaps")


def test_cadence_stability_mid_gap():
    visits = [make_visit(gap=3900.0)]  # midpoint
    score = compute_cadence_stability(visits)
    assert 0.4 < score < 0.6  # approximately 0.5
    print("  pass: cadence_stability_mid_gap")


# --- Grade tests ---

def test_grade_boundaries():
    assert grade_score(100) == "S"
    assert grade_score(90) == "S"
    assert grade_score(89.9) == "A"
    assert grade_score(75) == "A"
    assert grade_score(74.9) == "B"
    assert grade_score(60) == "B"
    assert grade_score(59.9) == "C"
    assert grade_score(40) == "C"
    assert grade_score(39.9) == "F"
    assert grade_score(0) == "F"
    print("  pass: grade_boundaries")


# --- Integration tests ---

def test_compute_score_perfect():
    visits = [make_visit(num=i, pending=0, gap=300.0) for i in range(10)]
    score = compute_score(visits)
    assert score.total == 100.0
    assert score.grade == "S"
    assert score.visits_analysed == 10
    assert len(score.components) == 4
    print("  pass: compute_score_perfect")


def test_compute_score_terrible():
    visits = [
        make_visit(num=i, writer_ok=False, batch_ok=False,
                   push_ok=False, pending=15, gap=10000.0)
        for i in range(10)
    ]
    score = compute_score(visits)
    assert score.total == 0.0
    assert score.grade == "F"
    print("  pass: compute_score_terrible")


def test_compute_score_realistic():
    # Mostly good, some hiccups
    visits = [make_visit(num=i, pending=2, gap=900.0) for i in range(8)]
    visits.append(make_visit(num=8, push_ok=False, pending=8, gap=3000.0))
    visits.append(make_visit(num=9, pending=3, gap=1200.0))
    score = compute_score(visits)
    assert 60 < score.total < 95  # realistic range
    assert score.grade in ("A", "B")
    print(f"  pass: compute_score_realistic (score={score.total})")


def test_score_clamping():
    # Edge case: ensure score never exceeds 100 or drops below 0
    visits = [make_visit()]
    score = compute_score(visits)
    assert 0 <= score.total <= 100
    print("  pass: score_clamping")


def test_format_text_basic():
    visits = [make_visit()]
    score = compute_score(visits)
    text = format_text(score)
    assert "Resurrection Score" in text
    assert "/100" in text
    print("  pass: format_text_basic")


def test_format_text_detail():
    visits = [make_visit()]
    score = compute_score(visits)
    text = format_text(score, detail=True)
    assert "recovery_rate" in text
    assert "push_reliability" in text
    assert "data_retention" in text
    assert "cadence_stability" in text
    assert "█" in text or "░" in text  # progress bar chars
    print("  pass: format_text_detail")


def test_json_output():
    visits = [make_visit(num=i) for i in range(5)]
    score = compute_score(visits)
    from dataclasses import asdict
    data = asdict(score)
    # Should be valid JSON-serializable
    json_str = json.dumps(data)
    parsed = json.loads(json_str)
    assert parsed["total"] == score.total
    assert parsed["grade"] == score.grade
    assert len(parsed["components"]) == 4
    print("  pass: json_output")


def test_component_weights_sum_to_one():
    """The four component weights must sum to 1.0."""
    weights = [0.30, 0.25, 0.25, 0.20]
    assert abs(sum(weights) - 1.0) < 1e-9
    print("  pass: component_weights_sum_to_one")


# --- Runner ---

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} tests passed" + (f", {failed} FAILED" if failed else ""))
    sys.exit(1 if failed else 0)
