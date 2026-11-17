"""Tests for iamai/process_collision.py — duplicate daemon detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.process_collision import (
    _extract_signature,
    collision_report,
    collision_risk,
    detect_groups,
    pick_survivor,
    pick_victims,
)


# ---------------------------------------------------------------------------
# _extract_signature
# ---------------------------------------------------------------------------

class TestExtractSignature:
    def test_writer_loop_qwen(self):
        sig = _extract_signature(
            "python3 tools/writer_loop.py --writer qwen --every 15"
        )
        assert sig == "writer_loop.py --writer qwen"

    def test_writer_loop_doubao(self):
        sig = _extract_signature(
            "python3 tools/writer_loop.py --writer doubao --every 30"
        )
        assert sig == "writer_loop.py --writer doubao"

    def test_writer_loop_ignores_cadence(self):
        sig1 = _extract_signature(
            "python3 tools/writer_loop.py --writer qwen --every 15"
        )
        sig2 = _extract_signature(
            "python3 tools/writer_loop.py --writer qwen --every 60"
        )
        assert sig1 == sig2

    def test_commit_batch(self):
        sig = _extract_signature(
            "python3 tools/commit_batch.py --watch --writer qwen --interval 600"
        )
        assert sig == "commit_batch.py --writer qwen"

    def test_commit_batch_doubao(self):
        sig = _extract_signature(
            "python3 tools/commit_batch.py --watch --writer doubao --interval 300"
        )
        assert sig == "commit_batch.py --writer doubao"

    def test_guoban_loop(self):
        sig = _extract_signature("python3 tools/guoban_loop.py")
        assert sig == "guoban_loop.py"

    def test_unknown_command(self):
        sig = _extract_signature("python3 -m http.server 8080")
        assert sig == "unknown"

    def test_empty_string(self):
        sig = _extract_signature("")
        assert sig == "unknown"

    def test_bare_python(self):
        sig = _extract_signature("python3")
        assert sig == "unknown"


# ---------------------------------------------------------------------------
# detect_groups
# ---------------------------------------------------------------------------

class TestDetectGroups:
    def test_single_pair(self):
        procs = [
            {"pid": 1, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 2, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
        ]
        groups = detect_groups(procs)
        assert len(groups) == 1
        assert groups[0]["count"] == 2
        assert groups[0]["signature"] == "writer_loop.py --writer qwen"

    def test_no_duplicates(self):
        procs = [
            {"pid": 1, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 2, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600"},
        ]
        groups = detect_groups(procs)
        assert groups == []

    def test_empty_input(self):
        assert detect_groups([]) == []

    def test_unknown_not_grouped(self):
        procs = [
            {"pid": 1, "command": "python3 -m http.server"},
            {"pid": 2, "command": "python3 -m http.server"},
        ]
        groups = detect_groups(procs)
        assert groups == []

    def test_different_writers_not_grouped(self):
        procs = [
            {"pid": 1, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 2, "command": "python3 tools/writer_loop.py --writer doubao --every 15"},
        ]
        groups = detect_groups(procs)
        assert groups == []

    def test_triple_instance(self):
        procs = [
            {"pid": 1, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 2, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 3, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
        ]
        groups = detect_groups(procs)
        assert len(groups) == 1
        assert groups[0]["count"] == 3

    def test_two_collision_groups(self):
        procs = [
            {"pid": 1, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 2, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 3, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600"},
            {"pid": 4, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600"},
        ]
        groups = detect_groups(procs)
        assert len(groups) == 2

    def test_mixed_known_and_unknown(self):
        procs = [
            {"pid": 1, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 2, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 3, "command": "python3 -m http.server"},
        ]
        groups = detect_groups(procs)
        assert len(groups) == 1
        assert groups[0]["count"] == 2


# ---------------------------------------------------------------------------
# collision_risk
# ---------------------------------------------------------------------------

class TestCollisionRisk:
    def test_no_groups(self):
        assert collision_risk([]) == 0.0

    def test_single_writer_collision(self):
        groups = [{"signature": "writer_loop.py --writer qwen", "count": 2, "instances": []}]
        risk = collision_risk(groups)
        assert risk == 0.35  # 0.25 (one extra) + 0.1 (writer premium)

    def test_single_batch_collision(self):
        groups = [{"signature": "commit_batch.py --writer qwen", "count": 2, "instances": []}]
        risk = collision_risk(groups)
        assert risk == 0.25  # 0.25 (one extra), no writer premium

    def test_double_collision(self):
        groups = [
            {"signature": "writer_loop.py --writer qwen", "count": 2, "instances": []},
            {"signature": "commit_batch.py --writer qwen", "count": 2, "instances": []},
        ]
        risk = collision_risk(groups)
        assert risk == 0.6  # (0.25 + 0.1) + 0.25

    def test_triple_instance_higher_risk(self):
        groups = [{"signature": "writer_loop.py --writer qwen", "count": 3, "instances": []}]
        risk = collision_risk(groups)
        assert risk == 0.6  # 2 * 0.25 + 0.1

    def test_capped_at_one(self):
        groups = [{"signature": "writer_loop.py --writer qwen", "count": 10, "instances": []}]
        risk = collision_risk(groups)
        assert risk == 1.0  # capped

    def test_risk_monotone(self):
        g1 = [{"signature": "writer_loop.py --writer qwen", "count": 2, "instances": []}]
        g2 = [{"signature": "writer_loop.py --writer qwen", "count": 3, "instances": []}]
        assert collision_risk(g2) > collision_risk(g1)


# ---------------------------------------------------------------------------
# pick_survivor
# ---------------------------------------------------------------------------

class TestPickSurvivor:
    def test_lowest_pid_wins(self):
        instances = [
            {"pid": 200, "command": "c", "uptime_s": 300},
            {"pid": 100, "command": "c", "uptime_s": 60},
        ]
        assert pick_survivor(instances)["pid"] == 100

    def test_same_pid_highest_uptime(self):
        instances = [
            {"pid": 100, "command": "c", "uptime_s": 60},
            {"pid": 100, "command": "c", "uptime_s": 300},
        ]
        assert pick_survivor(instances)["uptime_s"] == 300

    def test_single_instance(self):
        instances = [{"pid": 42, "command": "c", "uptime_s": 10}]
        assert pick_survivor(instances)["pid"] == 42

    def test_no_uptime_key(self):
        instances = [
            {"pid": 200, "command": "c"},
            {"pid": 100, "command": "c"},
        ]
        assert pick_survivor(instances)["pid"] == 100

    def test_three_instances(self):
        instances = [
            {"pid": 300, "command": "c", "uptime_s": 10},
            {"pid": 100, "command": "c", "uptime_s": 500},
            {"pid": 200, "command": "c", "uptime_s": 200},
        ]
        assert pick_survivor(instances)["pid"] == 100


# ---------------------------------------------------------------------------
# pick_victims
# ---------------------------------------------------------------------------

class TestPickVictims:
    def test_returns_non_survivors(self):
        instances = [
            {"pid": 100, "command": "c", "uptime_s": 300},
            {"pid": 200, "command": "c", "uptime_s": 60},
            {"pid": 300, "command": "c", "uptime_s": 10},
        ]
        victims = pick_victims(instances)
        assert len(victims) == 2
        assert {v["pid"] for v in victims} == {200, 300}

    def test_single_instance_no_victims(self):
        instances = [{"pid": 100, "command": "c"}]
        victims = pick_victims(instances)
        assert victims == []

    def test_pair(self):
        instances = [
            {"pid": 50, "command": "c", "uptime_s": 100},
            {"pid": 51, "command": "c", "uptime_s": 50},
        ]
        victims = pick_victims(instances)
        assert len(victims) == 1
        assert victims[0]["pid"] == 51


# ---------------------------------------------------------------------------
# collision_report
# ---------------------------------------------------------------------------

class TestCollisionReport:
    def test_clean_system(self):
        procs = [
            {"pid": 100, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 200, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600"},
        ]
        r = collision_report(procs)
        assert r["clean"] is True
        assert r["risk"] == 0.0
        assert r["recommendations"] == []
        assert r["total_processes"] == 2

    def test_collision_detected(self):
        procs = [
            {"pid": 100, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 300},
            {"pid": 200, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 60},
        ]
        r = collision_report(procs)
        assert r["clean"] is False
        assert r["risk"] > 0
        assert len(r["recommendations"]) == 1
        assert r["recommendations"][0]["kill_pid"] == 200
        assert r["recommendations"][0]["keep_pid"] == 100

    def test_full_scenario(self):
        """The exact situation from caretaker visit 685: two pairs."""
        procs = [
            {"pid": 8475, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 300},
            {"pid": 8476, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600", "uptime_s": 300},
            {"pid": 8518, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 60},
            {"pid": 8519, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600", "uptime_s": 60},
        ]
        r = collision_report(procs)
        assert r["clean"] is False
        assert r["total_processes"] == 4
        assert len(r["groups"]) == 2
        assert len(r["recommendations"]) == 2
        kill_pids = {rec["kill_pid"] for rec in r["recommendations"]}
        assert kill_pids == {8518, 8519}

    def test_empty_input(self):
        r = collision_report([])
        assert r["clean"] is True
        assert r["total_processes"] == 0

    def test_recommendation_has_reason(self):
        procs = [
            {"pid": 10, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 100},
            {"pid": 20, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 50},
        ]
        r = collision_report(procs)
        rec = r["recommendations"][0]
        assert "duplicate" in rec["reason"]
        assert "20" in rec["reason"]
        assert "10" in rec["reason"]

    def test_recommendation_signature(self):
        procs = [
            {"pid": 10, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
            {"pid": 20, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
        ]
        r = collision_report(procs)
        assert r["recommendations"][0]["signature"] == "writer_loop.py --writer qwen"


# ---------------------------------------------------------------------------
# Docstring examples (doctest-compatible)
# ---------------------------------------------------------------------------

class TestDocExamples:
    def test_quickstart(self):
        procs = [
            {"pid": 100, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 300},
            {"pid": 200, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 60},
            {"pid": 300, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600", "uptime_s": 300},
        ]
        groups = detect_groups(procs)
        assert len(groups) == 1
        assert groups[0]["signature"] == "writer_loop.py --writer qwen"
        assert collision_risk(groups) > 0
        assert pick_survivor(groups[0]["instances"])["pid"] == 100
