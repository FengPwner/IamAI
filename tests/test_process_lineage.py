"""Tests for iamai.process_lineage — track restart chains as a family tree.

Covers:
  1. Generation dataclass — lifespan, is_alive, to_dict, edge cases
  2. ProcessLineage.add / depth / current_generation / current_pid
  3. is_orphaned — single gen, linked chain, broken chain
  4. ancestors — chain traversal, missing parent, deep lineage
  5. Lifespan aggregation — total, average, all-alive edge case
  6. restart_causes — counting, None causes, mixed
  7. Serialization — to_list round-trip
  8. Integration — realistic overnight stall restart scenario
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from iamai.process_lineage import Generation, ProcessLineage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(offset_minutes: float = 0) -> datetime:
    """Return a UTC datetime offset by *offset_minutes* from a fixed epoch."""
    base = datetime(2026, 11, 22, 0, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=offset_minutes)


def _make_gen(pid=1, born_off=0, died_off=None, parent=None, cause=None, strokes=None):
    """Shorthand factory for Generation instances."""
    born = _ts(born_off)
    died = _ts(died_off) if died_off is not None else None
    return Generation(pid=pid, born=born, died=died, parent_pid=parent,
                      cause=cause, strokes=strokes)


# ===================================================================
# 1. Generation dataclass
# ===================================================================

class TestGeneration:

    def test_lifespan_alive(self):
        g = _make_gen(pid=1)
        assert g.lifespan_s() is None

    def test_lifespan_dead(self):
        g = _make_gen(pid=1, born_off=0, died_off=60)
        assert g.lifespan_s() == pytest.approx(3600.0)

    def test_lifespan_zero(self):
        g = _make_gen(pid=1, born_off=10, died_off=10)
        assert g.lifespan_s() == pytest.approx(0.0)

    def test_is_alive_true(self):
        g = _make_gen(pid=1)
        assert g.is_alive() is True

    def test_is_alive_false(self):
        g = _make_gen(pid=1, died_off=30)
        assert g.is_alive() is False

    def test_to_dict_keys(self):
        g = _make_gen(pid=42, born_off=0, died_off=10, parent=41,
                      cause="container", strokes=100)
        d = g.to_dict()
        assert set(d.keys()) == {"pid", "born", "died", "parent_pid", "cause", "strokes"}
        assert d["pid"] == 42
        assert d["parent_pid"] == 41
        assert d["cause"] == "container"
        assert d["strokes"] == 100

    def test_to_dict_none_fields(self):
        g = _make_gen(pid=1)
        d = g.to_dict()
        assert d["died"] is None
        assert d["parent_pid"] is None
        assert d["cause"] is None
        assert d["strokes"] is None

    def test_to_dict_isoformat(self):
        g = _make_gen(pid=1, born_off=0, died_off=5)
        d = g.to_dict()
        assert "2026-11-22" in d["born"]
        assert d["born"].endswith("+00:00")


# ===================================================================
# 2. ProcessLineage basic operations
# ===================================================================

class TestProcessLineageBasic:

    def test_empty_depth(self):
        tree = ProcessLineage()
        assert tree.depth() == 0

    def test_empty_current_generation(self):
        tree = ProcessLineage()
        assert tree.current_generation() == 0

    def test_empty_current_pid(self):
        tree = ProcessLineage()
        assert tree.current_pid() is None

    def test_add_single(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=100))
        assert tree.depth() == 1
        assert tree.current_generation() == 1
        assert tree.current_pid() == 100

    def test_add_multiple(self):
        tree = ProcessLineage()
        for i, pid in enumerate([10, 20, 30]):
            tree.add(_make_gen(pid=pid, born_off=i * 60))
        assert tree.depth() == 3
        assert tree.current_generation() == 3
        assert tree.current_pid() == 30

    def test_repr(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=7))
        r = repr(tree)
        assert "depth=1" in r
        assert "current_pid=7" in r


# ===================================================================
# 3. is_orphaned
# ===================================================================

class TestIsOrphaned:

    def test_empty(self):
        tree = ProcessLineage()
        assert tree.is_orphaned() is False

    def test_single_gen_not_orphaned(self):
        """A single generation is never considered orphaned."""
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1))
        assert tree.is_orphaned() is False

    def test_linked_chain_not_orphaned(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, died_off=60))
        tree.add(_make_gen(pid=2, born_off=65, parent=1))
        assert tree.is_orphaned() is False

    def test_broken_chain_is_orphaned(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, died_off=60))
        tree.add(_make_gen(pid=2, born_off=65, parent=None))  # no parent link
        assert tree.is_orphaned() is True

    def test_deep_chain_not_orphaned(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, died_off=10))
        tree.add(_make_gen(pid=2, born_off=12, died_off=20, parent=1))
        tree.add(_make_gen(pid=3, born_off=22, parent=2))
        assert tree.is_orphaned() is False


# ===================================================================
# 4. ancestors
# ===================================================================

class TestAncestors:

    def test_no_ancestors_for_root(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1))
        assert tree.ancestors(1) == []

    def test_single_parent(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, died_off=10))
        tree.add(_make_gen(pid=2, born_off=12, parent=1))
        assert tree.ancestors(2) == [1]

    def test_deep_chain(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, died_off=10))
        tree.add(_make_gen(pid=2, born_off=12, died_off=20, parent=1))
        tree.add(_make_gen(pid=3, born_off=22, died_off=30, parent=2))
        tree.add(_make_gen(pid=4, born_off=32, parent=3))
        assert tree.ancestors(4) == [3, 2, 1]

    def test_unknown_pid(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1))
        assert tree.ancestors(999) == []

    def test_broken_chain_stops(self):
        """Ancestor walk stops when parent_pid is None."""
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, died_off=10))
        tree.add(_make_gen(pid=2, born_off=12, died_off=20, parent=None))
        tree.add(_make_gen(pid=3, born_off=22, parent=2))
        assert tree.ancestors(3) == [2]


# ===================================================================
# 5. Lifespan aggregation
# ===================================================================

class TestLifespanAggregation:

    def test_total_lifespan(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, born_off=0, died_off=60))
        tree.add(_make_gen(pid=2, born_off=65, died_off=125))
        assert tree.total_lifespan_s() == pytest.approx(7200.0)

    def test_total_lifespan_ignores_alive(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, born_off=0, died_off=30))
        tree.add(_make_gen(pid=2, born_off=35))
        assert tree.total_lifespan_s() == pytest.approx(1800.0)

    def test_average_lifespan(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, born_off=0, died_off=60))
        tree.add(_make_gen(pid=2, born_off=65, died_off=125))
        assert tree.average_lifespan_s() == pytest.approx(3600.0)

    def test_average_lifespan_all_alive(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1))
        tree.add(_make_gen(pid=2))
        assert tree.average_lifespan_s() is None

    def test_average_lifespan_empty(self):
        tree = ProcessLineage()
        assert tree.average_lifespan_s() is None

    def test_total_lifespan_empty(self):
        tree = ProcessLineage()
        assert tree.total_lifespan_s() == pytest.approx(0.0)


# ===================================================================
# 6. restart_causes
# ===================================================================

class TestRestartCauses:

    def test_empty(self):
        tree = ProcessLineage()
        assert tree.restart_causes() == {}

    def test_single_cause(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, cause="container"))
        assert tree.restart_causes() == {"container": 1}

    def test_multiple_causes(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, cause="container"))
        tree.add(_make_gen(pid=2, cause="oom"))
        tree.add(_make_gen(pid=3, cause="container"))
        tree.add(_make_gen(pid=4, cause="manual"))
        assert tree.restart_causes() == {"container": 2, "oom": 1, "manual": 1}

    def test_none_cause_ignored(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, cause=None))
        tree.add(_make_gen(pid=2, cause="oom"))
        assert tree.restart_causes() == {"oom": 1}

    def test_all_none_causes(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1))
        tree.add(_make_gen(pid=2))
        assert tree.restart_causes() == {}


# ===================================================================
# 7. Serialization
# ===================================================================

class TestSerialization:

    def test_to_list_empty(self):
        tree = ProcessLineage()
        assert tree.to_list() == []

    def test_to_list_round_trip(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, born_off=0, died_off=60, cause="container", strokes=50))
        tree.add(_make_gen(pid=2, born_off=65, parent=1, cause=None, strokes=None))
        result = tree.to_list()
        assert len(result) == 2
        assert result[0]["pid"] == 1
        assert result[0]["cause"] == "container"
        assert result[0]["strokes"] == 50
        assert result[1]["pid"] == 2
        assert result[1]["parent_pid"] == 1
        assert result[1]["died"] is None

    def test_to_list_isoformat(self):
        tree = ProcessLineage()
        tree.add(_make_gen(pid=1, born_off=0, died_off=10))
        result = tree.to_list()
        assert isinstance(result[0]["born"], str)
        assert "T" in result[0]["born"]


# ===================================================================
# 8. Integration — realistic restart scenario
# ===================================================================

class TestIntegration:

    def test_overnight_stall_restart_chain(self):
        """Simulate the real pattern: container recycle -> manual restart -> alive."""
        tree = ProcessLineage()

        # Generation 1: ran for 4 hours, killed by container recycle
        tree.add(Generation(
            pid=1001,
            born=_ts(0),
            died=_ts(240),
            parent_pid=None,
            cause="container",
            strokes=400,
        ))

        # Generation 2: manual restart, ran 2 hours, OOM
        tree.add(Generation(
            pid=2002,
            born=_ts(245),
            died=_ts(365),
            parent_pid=1001,
            cause="oom",
            strokes=550,
        ))

        # Generation 3: caretaker restart, still alive
        tree.add(Generation(
            pid=3003,
            born=_ts(370),
            died=None,
            parent_pid=2002,
            cause=None,
            strokes=None,
        ))

        assert tree.depth() == 3
        assert tree.current_generation() == 3
        assert tree.current_pid() == 3003
        assert tree.is_orphaned() is False
        assert tree.ancestors(3003) == [2002, 1001]
        assert tree.total_lifespan_s() == pytest.approx((240 + 120) * 60.0)
        assert tree.average_lifespan_s() == pytest.approx((240 + 120) * 60.0 / 2)

        causes = tree.restart_causes()
        assert causes == {"container": 1, "oom": 1}

        # Serialization sanity
        data = tree.to_list()
        assert len(data) == 3
        assert data[-1]["died"] is None
        assert data[-1]["pid"] == 3003
