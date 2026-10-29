"""Tests for iamai.process_lineage — process restart chain tracker.

Caretaker visit 423 (2026-10-30): processes recycled by container scheduler,
PID lineage tracking needed to understand restart patterns.

Covers:
  - Generation lifecycle (birth, death, lifespan)
  - Lineage depth and current generation
  - Orphan detection
  - Ancestor chain traversal
  - Lifespan statistics
  - Restart cause aggregation
  - Serialization
"""

from datetime import datetime, timezone

import pytest

from iamai.process_lineage import Generation, ProcessLineage


# ---------------------------------------------------------------------------
# Generation basics
# ---------------------------------------------------------------------------

class TestGeneration:
    def test_alive_generation(self):
        g = Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc))
        assert g.is_alive()
        assert g.lifespan_s() is None

    def test_dead_generation(self):
        g = Generation(
            pid=100,
            born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc),
            died=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
            cause="container",
        )
        assert not g.is_alive()
        assert g.lifespan_s() == 3600.0

    def test_to_dict(self):
        g = Generation(
            pid=200,
            born=datetime(2026, 10, 30, 2, 0, 0, tzinfo=timezone.utc),
            died=None,
            parent_pid=100,
            cause=None,
            strokes=42,
        )
        d = g.to_dict()
        assert d["pid"] == 200
        assert d["parent_pid"] == 100
        assert d["strokes"] == 42
        assert d["died"] is None


# ---------------------------------------------------------------------------
# Lineage depth and tracking
# ---------------------------------------------------------------------------

class TestLineageDepth:
    def test_empty_lineage(self):
        tree = ProcessLineage()
        assert tree.depth() == 0
        assert tree.current_generation() == 0
        assert tree.current_pid() is None

    def test_single_generation(self):
        tree = ProcessLineage()
        g = Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc))
        tree.add(g)
        assert tree.depth() == 1
        assert tree.current_generation() == 1
        assert tree.current_pid() == 100

    def test_multiple_generations(self):
        tree = ProcessLineage()
        for i, pid in enumerate([100, 200, 300]):
            g = Generation(
                pid=pid,
                born=datetime(2026, 10, 30, i, 0, 0, tzinfo=timezone.utc),
            )
            tree.add(g)
        assert tree.depth() == 3
        assert tree.current_generation() == 3
        assert tree.current_pid() == 300


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------

class TestOrphanDetection:
    def test_single_is_not_orphan(self):
        tree = ProcessLineage()
        tree.add(Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)))
        assert not tree.is_orphaned()

    def test_connected_child_is_not_orphan(self):
        tree = ProcessLineage()
        tree.add(Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)))
        tree.add(Generation(
            pid=200,
            born=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
            parent_pid=100,
        ))
        assert not tree.is_orphaned()

    def test_orphan_child(self):
        tree = ProcessLineage()
        tree.add(Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)))
        tree.add(Generation(
            pid=200,
            born=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
            parent_pid=None,  # no parent link
        ))
        assert tree.is_orphaned()


# ---------------------------------------------------------------------------
# Ancestor traversal
# ---------------------------------------------------------------------------

class TestAncestors:
    def test_no_ancestors(self):
        tree = ProcessLineage()
        tree.add(Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)))
        assert tree.ancestors(100) == []

    def test_chain_of_three(self):
        tree = ProcessLineage()
        tree.add(Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)))
        tree.add(Generation(
            pid=200,
            born=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
            parent_pid=100,
        ))
        tree.add(Generation(
            pid=300,
            born=datetime(2026, 10, 30, 2, 0, 0, tzinfo=timezone.utc),
            parent_pid=200,
        ))
        assert tree.ancestors(300) == [200, 100]
        assert tree.ancestors(200) == [100]
        assert tree.ancestors(100) == []

    def test_unknown_pid(self):
        tree = ProcessLineage()
        assert tree.ancestors(999) == []


# ---------------------------------------------------------------------------
# Lifespan statistics
# ---------------------------------------------------------------------------

class TestLifespanStats:
    def test_all_alive(self):
        tree = ProcessLineage()
        tree.add(Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)))
        assert tree.total_lifespan_s() == 0.0
        assert tree.average_lifespan_s() is None

    def test_mixed_alive_and_dead(self):
        tree = ProcessLineage()
        tree.add(Generation(
            pid=100,
            born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc),
            died=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
        ))
        tree.add(Generation(
            pid=200,
            born=datetime(2026, 10, 30, 2, 0, 0, tzinfo=timezone.utc),
            died=datetime(2026, 10, 30, 2, 30, 0, tzinfo=timezone.utc),
        ))
        tree.add(Generation(pid=300, born=datetime(2026, 10, 30, 3, 0, 0, tzinfo=timezone.utc)))
        # 3600 + 1800 = 5400
        assert tree.total_lifespan_s() == 5400.0
        assert tree.average_lifespan_s() == 2700.0


# ---------------------------------------------------------------------------
# Restart cause aggregation
# ---------------------------------------------------------------------------

class TestRestartCauses:
    def test_no_causes(self):
        tree = ProcessLineage()
        tree.add(Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)))
        assert tree.restart_causes() == {}

    def test_mixed_causes(self):
        tree = ProcessLineage()
        tree.add(Generation(
            pid=100,
            born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc),
            died=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
            cause="container",
        ))
        tree.add(Generation(
            pid=200,
            born=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
            died=datetime(2026, 10, 30, 2, 0, 0, tzinfo=timezone.utc),
            cause="oom",
        ))
        tree.add(Generation(
            pid=300,
            born=datetime(2026, 10, 30, 2, 0, 0, tzinfo=timezone.utc),
            died=datetime(2026, 10, 30, 3, 0, 0, tzinfo=timezone.utc),
            cause="container",
        ))
        causes = tree.restart_causes()
        assert causes == {"container": 2, "oom": 1}


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_list(self):
        tree = ProcessLineage()
        tree.add(Generation(
            pid=100,
            born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc),
            parent_pid=None,
        ))
        tree.add(Generation(
            pid=200,
            born=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
            parent_pid=100,
        ))
        lst = tree.to_list()
        assert len(lst) == 2
        assert lst[0]["pid"] == 100
        assert lst[1]["parent_pid"] == 100
