#!/usr/bin/env python3
"""Tests for iamai/process_lineage.py — 33 tests.

The process_lineage module tracks restart chains as a family tree,
recording PID successions, lifespans, and restart causes.  Tests cover:

1. Generation dataclass — lifespan_s, is_alive, to_dict
2. ProcessLineage.add / depth / current_generation
3. current_pid — empty and populated cases
4. is_orphaned — single, connected, disconnected lineages
5. ancestors — chain traversal
6. total_lifespan_s / average_lifespan_s — arithmetic
7. restart_causes — counting by cause
8. to_list / repr — serialisation
9. Edge cases — empty lineage, all-alive, single generation
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.process_lineage import Generation, ProcessLineage


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _dt(hour: int, minute: int = 0) -> datetime:
    """Shortcut for 2026-11-23 UTC timestamps."""
    return datetime(2026, 11, 23, hour, minute, 0, tzinfo=timezone.utc)


def _gen(pid, born_h, died_h=None, parent=None, cause=None, strokes=None):
    """Build a Generation with compact hour-based timestamps."""
    born = _dt(born_h)
    died = _dt(died_h) if died_h is not None else None
    return Generation(pid=pid, born=born, died=died,
                      parent_pid=parent, cause=cause, strokes=strokes)


# ===========================================================================
# Generation dataclass
# ===========================================================================

class TestGenerationLifespan(unittest.TestCase):
    """Generation.lifespan_s() — seconds between born and died."""

    def test_alive_returns_none(self):
        g = _gen(1, born_h=0)
        self.assertIsNone(g.lifespan_s())

    def test_one_hour(self):
        g = _gen(1, born_h=0, died_h=1)
        self.assertAlmostEqual(g.lifespan_s(), 3600.0)

    def test_zero_duration(self):
        g = _gen(1, born_h=5, died_h=5)
        self.assertAlmostEqual(g.lifespan_s(), 0.0)

    def test_fractional_hours(self):
        born = datetime(2026, 11, 23, 0, 0, 0, tzinfo=timezone.utc)
        died = datetime(2026, 11, 23, 0, 30, 0, tzinfo=timezone.utc)
        g = Generation(pid=1, born=born, died=died)
        self.assertAlmostEqual(g.lifespan_s(), 1800.0)


class TestGenerationIsAlive(unittest.TestCase):
    """Generation.is_alive() — True when died is None."""

    def test_alive(self):
        self.assertTrue(_gen(1, born_h=0).is_alive())

    def test_dead(self):
        self.assertFalse(_gen(1, born_h=0, died_h=1).is_alive())


class TestGenerationToDict(unittest.TestCase):
    """Generation.to_dict() — serialisation round-trip."""

    def test_full_fields(self):
        g = _gen(42, born_h=2, died_h=4, parent=10, cause="oom", strokes=500)
        d = g.to_dict()
        self.assertEqual(d["pid"], 42)
        self.assertIn("2026-11-23", d["born"])
        self.assertIn("2026-11-23", d["died"])
        self.assertEqual(d["parent_pid"], 10)
        self.assertEqual(d["cause"], "oom")
        self.assertEqual(d["strokes"], 500)

    def test_none_fields(self):
        g = _gen(1, born_h=0)
        d = g.to_dict()
        self.assertIsNone(d["died"])
        self.assertIsNone(d["parent_pid"])
        self.assertIsNone(d["cause"])
        self.assertIsNone(d["strokes"])


# ===========================================================================
# ProcessLineage — basic operations
# ===========================================================================

class TestLineageAddDepth(unittest.TestCase):
    """ProcessLineage.add / depth / current_generation."""

    def test_empty(self):
        tree = ProcessLineage()
        self.assertEqual(tree.depth(), 0)
        self.assertEqual(tree.current_generation(), 0)

    def test_single(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0))
        self.assertEqual(tree.depth(), 1)
        self.assertEqual(tree.current_generation(), 1)

    def test_three_generations(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0, died_h=1, cause="container"))
        tree.add(_gen(200, born_h=1, died_h=3, parent=100, cause="oom"))
        tree.add(_gen(300, born_h=3, parent=200))
        self.assertEqual(tree.depth(), 3)
        self.assertEqual(tree.current_generation(), 3)


class TestCurrentPid(unittest.TestCase):
    """ProcessLineage.current_pid()."""

    def test_empty_returns_none(self):
        tree = ProcessLineage()
        self.assertIsNone(tree.current_pid())

    def test_returns_latest(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0, died_h=1))
        tree.add(_gen(200, born_h=1))
        self.assertEqual(tree.current_pid(), 200)


# ===========================================================================
# is_orphaned
# ===========================================================================

class TestIsOrphaned(unittest.TestCase):
    """ProcessLineage.is_orphaned() — latest has no parent and depth > 1."""

    def test_single_generation_not_orphaned(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0))
        self.assertFalse(tree.is_orphaned())

    def test_connected_not_orphaned(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0, died_h=1))
        tree.add(_gen(200, born_h=1, parent=100))
        self.assertFalse(tree.is_orphaned())

    def test_disconnected_is_orphaned(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0, died_h=1))
        tree.add(_gen(200, born_h=1, parent=None))  # no parent link
        self.assertTrue(tree.is_orphaned())

    def test_empty_not_orphaned(self):
        tree = ProcessLineage()
        self.assertFalse(tree.is_orphaned())


# ===========================================================================
# ancestors
# ===========================================================================

class TestAncestors(unittest.TestCase):
    """ProcessLineage.ancestors(pid) — chain of parent PIDs."""

    def test_single_no_parent(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0))
        self.assertEqual(tree.ancestors(100), [])

    def test_three_deep(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0, died_h=1))
        tree.add(_gen(200, born_h=1, died_h=3, parent=100))
        tree.add(_gen(300, born_h=3, parent=200))
        self.assertEqual(tree.ancestors(300), [200, 100])

    def test_unknown_pid(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0))
        self.assertEqual(tree.ancestors(999), [])

    def test_broken_chain(self):
        tree = ProcessLineage()
        tree.add(_gen(100, born_h=0, died_h=1))
        tree.add(_gen(300, born_h=1, parent=200))  # 200 not in tree
        self.assertEqual(tree.ancestors(300), [200])


# ===========================================================================
# lifespan aggregation
# ===========================================================================

class TestTotalLifespan(unittest.TestCase):
    """ProcessLineage.total_lifespan_s()."""

    def test_empty(self):
        tree = ProcessLineage()
        self.assertAlmostEqual(tree.total_lifespan_s(), 0.0)

    def test_two_dead_one_alive(self):
        tree = ProcessLineage()
        tree.add(_gen(1, born_h=0, died_h=1))     # 3600s
        tree.add(_gen(2, born_h=1, died_h=3))     # 7200s
        tree.add(_gen(3, born_h=3))                # alive → skip
        self.assertAlmostEqual(tree.total_lifespan_s(), 10800.0)

    def test_all_alive(self):
        tree = ProcessLineage()
        tree.add(_gen(1, born_h=0))
        tree.add(_gen(2, born_h=1))
        self.assertAlmostEqual(tree.total_lifespan_s(), 0.0)


class TestAverageLifespan(unittest.TestCase):
    """ProcessLineage.average_lifespan_s()."""

    def test_none_when_all_alive(self):
        tree = ProcessLineage()
        tree.add(_gen(1, born_h=0))
        self.assertIsNone(tree.average_lifespan_s())

    def test_empty_returns_none(self):
        tree = ProcessLineage()
        self.assertIsNone(tree.average_lifespan_s())

    def test_mixed(self):
        tree = ProcessLineage()
        tree.add(_gen(1, born_h=0, died_h=2))  # 7200s
        tree.add(_gen(2, born_h=2, died_h=4))  # 7200s
        tree.add(_gen(3, born_h=4))             # alive
        self.assertAlmostEqual(tree.average_lifespan_s(), 7200.0)


# ===========================================================================
# restart_causes
# ===========================================================================

class TestRestartCauses(unittest.TestCase):
    """ProcessLineage.restart_causes() — count by cause."""

    def test_empty(self):
        tree = ProcessLineage()
        self.assertEqual(tree.restart_causes(), {})

    def test_multiple_causes(self):
        tree = ProcessLineage()
        tree.add(_gen(1, born_h=0, died_h=1, cause="container"))
        tree.add(_gen(2, born_h=1, died_h=2, cause="oom"))
        tree.add(_gen(3, born_h=2, died_h=3, cause="container"))
        tree.add(_gen(4, born_h=3, died_h=4, cause="manual"))
        tree.add(_gen(5, born_h=4))
        counts = tree.restart_causes()
        self.assertEqual(counts["container"], 2)
        self.assertEqual(counts["oom"], 1)
        self.assertEqual(counts["manual"], 1)

    def test_no_cause_not_counted(self):
        tree = ProcessLineage()
        tree.add(_gen(1, born_h=0, died_h=1, cause=None))
        self.assertEqual(tree.restart_causes(), {})


# ===========================================================================
# serialisation
# ===========================================================================

class TestToList(unittest.TestCase):
    """ProcessLineage.to_list() — list of dicts."""

    def test_empty(self):
        tree = ProcessLineage()
        self.assertEqual(tree.to_list(), [])

    def test_round_trip(self):
        tree = ProcessLineage()
        tree.add(_gen(10, born_h=0, died_h=1, cause="container", strokes=100))
        tree.add(_gen(20, born_h=1, parent=10))
        result = tree.to_list()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["pid"], 10)
        self.assertEqual(result[1]["pid"], 20)
        self.assertIsNone(result[1]["died"])


class TestRepr(unittest.TestCase):
    """ProcessLineage.__repr__."""

    def test_repr(self):
        tree = ProcessLineage()
        tree.add(_gen(42, born_h=0))
        r = repr(tree)
        self.assertIn("depth=1", r)
        self.assertIn("current_pid=42", r)


if __name__ == "__main__":
    unittest.main()
