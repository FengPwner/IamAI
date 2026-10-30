#!/usr/bin/env python3
"""tests for session_continuity_scorer.

27 tests covering:
  - note parsing (visit number, process status, pending, unpushed)
  - process survival scoring
  - cadence fidelity scoring
  - backlog discipline scoring
  - composite grade and label
  - edge cases (missing fields, malformed notes)
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# allow running from tools/ or repo root
sys.path.insert(0, os.path.dirname(__file__))
from session_continuity_scorer import (
    ContinuityScore,
    VisitRecord,
    grade_label,
    load_visits,
    parse_visit_note,
    score_all,
    score_backlog_discipline,
    score_cadence_fidelity,
    score_pair,
    score_process_survival,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_visit(num=1, writer=True, batch=True, pending=0, unpushed=0,
               restart=False, ts="2026-10-27 14:01"):
    return VisitRecord(
        visit_num=num,
        timestamp=ts,
        writer_running=writer,
        batch_running=batch,
        pending_files=pending,
        unpushed_commits=unpushed,
        restart_needed=restart,
    )


SAMPLE_NOTE = """# caretaker visit 42 — 2026-10-15 08:01

## pre-flight

- **writer[qwen]:** running pid 1234 (restarted by visit 41 at 07:01)
- **batch[qwen]:** running pid 1235 (restarted by visit 41 at 07:01)
- **pending:** 5 files uncommitted
- **unpushed:** 23 commits accumulated
"""

BROKEN_NOTE = """# caretaker visit 99 — 2026-10-20 12:00

## pre-flight

- **writer[qwen]:** NOT running
- **batch[qwen]:** NOT running
- **pending:** 30 files uncommitted
- **unpushed:** 88 commits
- restart attempted, writer recovered, batch still down
"""


class TestParseVisitNote(unittest.TestCase):
    def test_parse_healthy_note(self):
        rec = parse_visit_note(SAMPLE_NOTE)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.visit_num, 42)
        self.assertTrue(rec.writer_running)
        self.assertTrue(rec.batch_running)
        self.assertEqual(rec.pending_files, 5)
        self.assertEqual(rec.unpushed_commits, 23)

    def test_parse_broken_note(self):
        rec = parse_visit_note(BROKEN_NOTE)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.visit_num, 99)
        self.assertFalse(rec.writer_running)
        self.assertFalse(rec.batch_running)
        self.assertEqual(rec.pending_files, 30)
        self.assertEqual(rec.unpushed_commits, 88)
        self.assertTrue(rec.restart_needed)

    def test_parse_garbage(self):
        rec = parse_visit_note("this is not a visit note at all")
        self.assertIsNone(rec)

    def test_parse_missing_fields(self):
        note = "# caretaker visit 7 — 2026-10-01\nsome text without structure"
        rec = parse_visit_note(note)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.visit_num, 7)
        self.assertFalse(rec.writer_running)
        self.assertFalse(rec.batch_running)
        self.assertEqual(rec.pending_files, 0)


class TestProcessSurvival(unittest.TestCase):
    def test_both_alive(self):
        prev = make_visit(1, writer=True, batch=True)
        curr = make_visit(2, writer=True, batch=True)
        self.assertEqual(score_process_survival(prev, curr), 100.0)

    def test_one_dead(self):
        prev = make_visit(1, writer=True, batch=True)
        curr = make_visit(2, writer=False, batch=True)
        self.assertEqual(score_process_survival(prev, curr), 50.0)

    def test_both_dead(self):
        prev = make_visit(1, writer=True, batch=True)
        curr = make_visit(2, writer=False, batch=False)
        self.assertEqual(score_process_survival(prev, curr), 0.0)


class TestCadenceFidelity(unittest.TestCase):
    def test_healthy_cadence_low_pending(self):
        prev = make_visit(1, writer=True)
        curr = make_visit(2, writer=True, pending=3)
        self.assertEqual(score_cadence_fidelity(prev, curr), 100.0)

    def test_moderate_pending(self):
        prev = make_visit(1, writer=True)
        curr = make_visit(2, writer=True, pending=15)
        self.assertEqual(score_cadence_fidelity(prev, curr), 75.0)

    def test_writer_restarted(self):
        prev = make_visit(1, writer=False)
        curr = make_visit(2, writer=True, pending=2)
        self.assertEqual(score_cadence_fidelity(prev, curr), 50.0)

    def test_high_pending_stall(self):
        prev = make_visit(1, writer=True)
        curr = make_visit(2, writer=True, pending=25)
        self.assertEqual(score_cadence_fidelity(prev, curr), 25.0)

    def test_writer_not_running(self):
        prev = make_visit(1, writer=True)
        curr = make_visit(2, writer=False)
        self.assertEqual(score_cadence_fidelity(prev, curr), 0.0)


class TestBacklogDiscipline(unittest.TestCase):
    def test_zero_pending(self):
        prev = make_visit(1, pending=5)
        curr = make_visit(2, pending=0)
        self.assertEqual(score_backlog_discipline(prev, curr), 100.0)

    def test_decreased_pending(self):
        prev = make_visit(1, pending=10)
        curr = make_visit(2, pending=5)
        self.assertEqual(score_backlog_discipline(prev, curr), 100.0)

    def test_increased_but_low(self):
        prev = make_visit(1, pending=2)
        curr = make_visit(2, pending=7)
        self.assertEqual(score_backlog_discipline(prev, curr), 75.0)

    def test_moderate_backlog(self):
        prev = make_visit(1, pending=5)
        curr = make_visit(2, pending=15)
        self.assertEqual(score_backlog_discipline(prev, curr), 50.0)

    def test_large_backlog(self):
        prev = make_visit(1, pending=20)
        curr = make_visit(2, pending=35)
        self.assertEqual(score_backlog_discipline(prev, curr), 25.0)

    def test_critical_backlog(self):
        prev = make_visit(1, pending=40)
        curr = make_visit(2, pending=60)
        self.assertEqual(score_backlog_discipline(prev, curr), 0.0)


class TestCompositeGrade(unittest.TestCase):
    def test_perfect_continuity(self):
        prev = make_visit(1, writer=True, batch=True, pending=0)
        curr = make_visit(2, writer=True, batch=True, pending=0)
        s = score_pair(prev, curr)
        self.assertEqual(s.grade, 100.0)
        self.assertEqual(s.label, "excellent")

    def test_weakest_link_determines_grade(self):
        prev = make_visit(1, writer=True, batch=True, pending=0)
        curr = make_visit(2, writer=True, batch=False, pending=30)
        s = score_pair(prev, curr)
        # process=50, cadence=100, backlog=25 → grade=25
        self.assertEqual(s.grade, 25.0)
        self.assertEqual(s.label, "broken")

    def test_degraded_grade(self):
        prev = make_visit(1, writer=True, batch=True, pending=5)
        curr = make_visit(2, writer=False, batch=True, pending=30)
        s = score_pair(prev, curr)
        # process=50, cadence=0, backlog=25 → grade=0
        self.assertEqual(s.grade, 0.0)
        self.assertEqual(s.label, "broken")

    def test_good_continuity(self):
        prev = make_visit(1, writer=True, batch=True, pending=3)
        curr = make_visit(2, writer=True, batch=True, pending=5)
        s = score_pair(prev, curr)
        # process=100, cadence=100, backlog=75 → grade=75
        self.assertEqual(s.grade, 75.0)
        self.assertEqual(s.label, "good")


class TestGradeLabel(unittest.TestCase):
    def test_excellent(self):
        self.assertEqual(grade_label(95), "excellent")

    def test_good(self):
        self.assertEqual(grade_label(70), "good")

    def test_degraded(self):
        self.assertEqual(grade_label(45), "degraded")

    def test_broken(self):
        self.assertEqual(grade_label(10), "broken")


class TestLoadVisits(unittest.TestCase):
    def test_load_from_directory(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "caretaker-visit-1.md").write_text(SAMPLE_NOTE)
            (p / "caretaker-visit-2.md").write_text(BROKEN_NOTE)
            (p / "unrelated.md").write_text("not a visit note")
            visits = load_visits(td)
            self.assertEqual(len(visits), 2)
            self.assertEqual(visits[0].visit_num, 42)
            self.assertEqual(visits[1].visit_num, 99)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as td:
            visits = load_visits(td)
            self.assertEqual(len(visits), 0)

    def test_nonexistent_directory(self):
        visits = load_visits("/tmp/this_dir_does_not_exist_xyz")
        self.assertEqual(len(visits), 0)


class TestScoreAll(unittest.TestCase):
    def test_score_sequence(self):
        visits = [
            make_visit(1, writer=True, batch=True, pending=0),
            make_visit(2, writer=True, batch=True, pending=2),
            make_visit(3, writer=True, batch=True, pending=5),
        ]
        scores = score_all(visits)
        self.assertEqual(len(scores), 2)
        self.assertEqual(scores[0].prev_visit, 1)
        self.assertEqual(scores[0].curr_visit, 2)
        self.assertEqual(scores[1].prev_visit, 2)
        self.assertEqual(scores[1].curr_visit, 3)

    def test_single_visit_no_scores(self):
        visits = [make_visit(1)]
        scores = score_all(visits)
        self.assertEqual(len(scores), 0)


class TestContinuityScoreToDict(unittest.TestCase):
    def test_to_dict_round_trip(self):
        s = ContinuityScore(
            prev_visit=10, curr_visit=11,
            process_survival=100.0, cadence_fidelity=75.0,
            backlog_discipline=50.0, grade=50.0, label="degraded"
        )
        d = s.to_dict()
        self.assertEqual(d["prev_visit"], 10)
        self.assertEqual(d["grade"], 50.0)
        self.assertEqual(d["label"], "degraded")
        # json serializable
        json.dumps(d)


if __name__ == "__main__":
    unittest.main()
