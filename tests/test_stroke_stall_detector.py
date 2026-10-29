"""Tests for the stroke stall detector.

Covers both stall modes (silence and repetition), edge cases with
empty/malformed data, and the combined diagnosis pipeline.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.stroke_stall_detector import (
    load_strokes,
    measure_silence,
    measure_repetition,
    diagnose,
    _similarity,
    _extract_text,
    REPETITION_RATIO_THRESHOLD,
    SILENCE_MULTIPLIER,
)


# -- helpers ---------------------------------------------------------------

def _stroke(text: str, seq: int = 0, at: str | None = None) -> dict:
    """Build a minimal stroke dict."""
    if at is None:
        at = datetime.now(timezone.utc).isoformat()
    return {"seq": seq, "at": at, "kind": "note", "text": text}


def _stroke_ago(text: str, seconds_ago: float, seq: int = 0) -> dict:
    """Build a stroke with a timestamp N seconds in the past."""
    at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return _stroke(text, seq=seq, at=at.isoformat())


# -- _similarity -----------------------------------------------------------

class TestSimilarity:
    def test_identical_strings(self):
        assert _similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _similarity("abcdef", "xyz123") < 0.3

    def test_empty_both(self):
        assert _similarity("", "") == 1.0

    def test_one_empty(self):
        assert _similarity("hello", "") == 0.0
        assert _similarity("", "hello") == 0.0

    def test_near_duplicate(self):
        a = "the quick brown fox jumps over the lazy dog"
        b = "the quick brown fox jumps over the lazy cat"
        assert _similarity(a, b) > 0.8


# -- _extract_text ---------------------------------------------------------

class TestExtractText:
    def test_text_field(self):
        assert _extract_text({"text": "hello"}) == "hello"

    def test_content_field_fallback(self):
        assert _extract_text({"content": "fallback"}) == "fallback"

    def test_empty_dict(self):
        assert _extract_text({}) == ""

    def test_none_text(self):
        assert _extract_text({"text": None}) == ""


# -- load_strokes ----------------------------------------------------------

class TestLoadStrokes:
    def test_load_valid_jsonl(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq":1,"at":"2026-01-01T00:00:00+00:00","kind":"note","text":"a"}\n'
            '{"seq":2,"at":"2026-01-01T00:01:00+00:00","kind":"note","text":"b"}\n'
        )
        strokes = load_strokes(f)
        assert len(strokes) == 2
        assert strokes[0]["text"] == "a"
        assert strokes[1]["seq"] == 2

    def test_tolerates_malformed_lines(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq":1,"text":"good"}\n'
            'this is not json\n'
            '{"seq":2,"text":"also good"}\n'
            '\n'
        )
        strokes = load_strokes(f)
        assert len(strokes) == 2

    def test_missing_file_returns_empty(self, tmp_path: Path):
        strokes = load_strokes(tmp_path / "nonexistent.jsonl")
        assert strokes == []

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        assert load_strokes(f) == []


# -- measure_silence -------------------------------------------------------

class TestMeasureSilence:
    def test_no_strokes_means_silent(self):
        result = measure_silence([], cadence_s=15.0)
        assert result["silent"] is True
        assert result["gap_s"] is None

    def test_recent_stroke_not_silent(self):
        strokes = [_stroke_ago("fresh content", seconds_ago=5)]
        result = measure_silence(strokes, cadence_s=15.0)
        assert result["silent"] is False
        assert result["gap_s"] is not None
        assert result["gap_s"] < 15

    def test_old_stroke_is_silent(self):
        strokes = [_stroke_ago("old content", seconds_ago=100)]
        result = measure_silence(strokes, cadence_s=15.0)
        assert result["silent"] is True
        assert result["gap_s"] > 30  # 2x cadence

    def test_threshold_is_2x_cadence(self):
        result = measure_silence([], cadence_s=20.0)
        assert result["threshold_s"] == 40.0

    def test_custom_now(self):
        fixed_now = time.time()
        strokes = [_stroke_ago("content", seconds_ago=50)]
        result = measure_silence(strokes, cadence_s=15.0, now=fixed_now)
        assert result["gap_s"] == pytest.approx(50.0, abs=2)

    def test_malformed_timestamp_not_silent(self):
        strokes = [{"seq": 1, "at": "not-a-date", "text": "x"}]
        result = measure_silence(strokes, cadence_s=15.0)
        # gap_s should be None because timestamp can't be parsed
        assert result["gap_s"] is None
        assert result["silent"] is False  # None gap ≠ silent


# -- measure_repetition ----------------------------------------------------

class TestMeasureRepetition:
    def test_all_unique_content(self):
        topics = [
            "distributed consensus requires a majority quorum to proceed",
            "garbage collection pauses are bounded by heap size and scan rate",
            "eventual consistency trades latency for availability in partitions",
            "bloom filters give probabilistic membership with no false negatives",
            "write-ahead logs ensure durability before acknowledging commits",
            "backpressure propagates upstream when downstream buffers fill up",
            "idempotency keys prevent duplicate side effects on retry",
            "circuit breakers trip after consecutive failures exceed threshold",
            "consistent hashing minimizes key redistribution on node changes",
            "compensating transactions undo partial work in saga patterns",
        ]
        strokes = [_stroke(t, seq=i) for i, t in enumerate(topics)]
        result = measure_repetition(strokes)
        assert result["stalled"] is False
        assert result["ratio"] < 0.3

    def test_all_identical_is_stalled(self):
        strokes = [
            _stroke("the same thing over and over", seq=i)
            for i in range(20)
        ]
        result = measure_repetition(strokes)
        assert result["stalled"] is True
        assert result["ratio"] > REPETITION_RATIO_THRESHOLD

    def test_near_duplicates_detected(self):
        base = "chunk_text.py is already in the pool of 9 modules, nothing new to add there"
        strokes = []
        for i in range(20):
            # Slight variation — just changing the stroke number
            text = f"{base} -- stroke {4860 + i * 6}"
            strokes.append(_stroke(text, seq=i))
        result = measure_repetition(strokes)
        assert result["stalled"] is True
        assert result["duplicates"] > 10

    def test_empty_input(self):
        result = measure_repetition([])
        assert result["stalled"] is False
        assert result["total"] == 0

    def test_single_stroke(self):
        result = measure_repetition([_stroke("only one")])
        assert result["stalled"] is False
        assert result["duplicates"] == 0

    def test_window_limits_scope(self):
        # 100 strokes: first 50 are identical, last 50 are unique
        strokes = []
        for i in range(50):
            strokes.append(_stroke("repeated content", seq=i))
        unique_topics = [
            "tcp congestion control adjusts window size on packet loss",
            "http2 multiplexes streams over a single tcp connection",
            "dns resolution walks the hierarchy from root to authoritative",
            "tls handshake negotiates cipher suite and exchanges keys",
            "websocket upgrades http into a persistent bidirectional channel",
            "grpc serializes protobuf messages over http2 streams",
            "load balancers distribute requests using consistent hashing",
            "circuit breakers prevent cascade failures across services",
            "rate limiting uses token buckets to smooth request bursts",
            "health checks distinguish live nodes from partitioned ones",
            "service mesh injects sidecars to handle cross cutting concerns",
            "distributed tracing correlates spans across process boundaries",
            "feature flags decouple deployment from release to users",
            "canary deploys route a small fraction of traffic to new versions",
            "blue green switching flips all traffic between two environments",
            "rollback reverts to the previous known good deployment artifact",
            "infrastructure as code stores environment config in version control",
            "container orchestration schedules pods onto available worker nodes",
            "sidecar proxies handle mutual tls between microservices",
            "event sourcing persists state changes as an append only log",
            "command query responsibility segregation splits read and write paths",
            "saga patterns coordinate distributed transactions with compensations",
            "idempotency tokens prevent duplicate processing on message redelivery",
            "dead letter queues capture messages that exceed retry budgets",
            "exponential backoff with jitter spreads retry attempts over time",
            "bulkheads isolate resource pools so one failure does not cascade",
            "timeout budgets propagate remaining time across service calls",
            "retry storms amplify load precisely when the system is struggling",
            "graceful degradation returns partial results instead of total failure",
            "chaos engineering injects faults to validate resilience mechanisms",
            "fault injection tests run in production with controlled blast radius",
            "observability combines metrics logs and traces into one picture",
            "structured logging emits machine parseable fields for aggregation",
            "percentile histograms capture latency distributions without sampling",
            "alert fatigue grows when most notifications require no action",
            "on call rotation ensures someone is always reachable at three am",
            "postmortems document root cause and preventive action items",
            "blameless culture encourages honest incident reporting",
            "error budgets balance reliability investment against feature velocity",
            "service level objectives define the reliability target per quarter",
            "service level indicators measure the actual user facing behaviour",
            "service level agreements encode consequences of missing the target",
            "capacity planning projects resource needs from growth trends",
            "load testing pushes the system past expected peak to find limits",
            "stress testing identifies the breaking point under sustained pressure",
            "soak testing runs the system under load for hours to find leaks",
            "shadow traffic replays production requests against a new version",
            "dark launching deploys features hidden behind feature flags",
            "progressive delivery increases rollout percentage in small steps",
            "gitops automates deployments from pull requests to the config repo",
        ]
        for i in range(50, 100):
            strokes.append(_stroke(unique_topics[i - 50], seq=i))
        # With window=50, only the last 50 (unique) should be examined
        result = measure_repetition(strokes, window=50)
        assert result["stalled"] is False
        assert result["total"] == 50

    def test_duplicate_texts_capped_at_5(self):
        strokes = [_stroke("same thing", seq=i) for i in range(30)]
        result = measure_repetition(strokes)
        assert len(result["duplicate_texts"]) <= 5


# -- diagnose --------------------------------------------------------------

class TestDiagnose:
    def test_healthy_repo(self):
        topics = [
            "merkle trees let you verify large datasets with logarithmic proofs",
            "paxos reaches consensus when a majority of acceptors respond",
            "crdt lattices converge without coordination across replicas",
            "raft elects a leader who serializes all log appends",
            "gossip protocols spread membership updates in logarithmic rounds",
            "two phase commit blocks until every participant votes yes or no",
            "vector clocks track causal ordering without a global clock",
            "lease based locks expire automatically to prevent deadlocks",
            "sharding spreads write load across independent partitions",
            "read repair fixes stale replicas lazily on each read path",
            "anti entropy runs periodic merkle tree comparisons between peers",
            "hinted handoff stores writes temporarily for a recovering node",
            "tombstones mark deletions and propagate through the cluster",
            "quorum reads and writes overlap to guarantee fresh data",
            "tunable consistency lets each query choose its own latency cost",
            "failure detectors use phi accrual to distinguish slow from dead",
            "epoch based reconfiguration prevents split brain during transitions",
            "log structured merge trees absorb write bursts in sorted runs",
            "compaction merges overlapping sstables to reduce read amplification",
            "bloom filters skip disk seeks for keys that definitely are absent",
        ]
        strokes = [
            _stroke_ago(topics[i], seconds_ago=10 + i * 0.1, seq=i)
            for i in range(20)
        ]
        report = diagnose(strokes, cadence_s=15.0)
        assert report["stalled"] is False
        assert report["severity"] == "healthy"
        assert report["exit_code"] == 0

    def test_silence_stall(self):
        strokes = [_stroke_ago("old content", seconds_ago=500)]
        report = diagnose(strokes, cadence_s=15.0)
        assert report["stalled"] is True
        assert report["severity"] in ("high", "critical")
        assert "silence" in report["summary"]
        assert report["exit_code"] in (2, 3)

    def test_repetition_stall(self):
        strokes = [
            _stroke_ago("the exact same idea repeated", seconds_ago=5 + i, seq=i)
            for i in range(30)
        ]
        report = diagnose(strokes, cadence_s=15.0)
        assert report["stalled"] is True
        assert "repetition" in report["summary"]
        assert report["exit_code"] in (1, 3)

    def test_both_stalls_is_critical(self):
        # Old timestamps + identical content
        strokes = [
            _stroke_ago("repeated", seconds_ago=500 + i, seq=i)
            for i in range(30)
        ]
        report = diagnose(strokes, cadence_s=15.0)
        assert report["stalled"] is True
        assert report["severity"] == "critical"
        assert report["exit_code"] == 3

    def test_empty_strokes(self):
        report = diagnose([], cadence_s=15.0)
        assert report["stalled"] is True  # silence stall with no strokes
        assert report["exit_code"] >= 2

    def test_summary_is_human_readable(self):
        strokes = [_stroke_ago("fresh", seconds_ago=5, seq=1)]
        report = diagnose(strokes, cadence_s=15.0)
        assert "no stall" in report["summary"]


# -- integration with real file format ------------------------------------

class TestIntegration:
    def test_round_trip_with_jsonl(self, tmp_path: Path):
        """Write strokes to JSONL, load them back, diagnose."""
        f = tmp_path / "strokes.jsonl"
        topics = [
            "append only logs force you to be wrong in public",
            "commit history is the only honest documentation",
            "naming is hard because a bad name is cheap to type",
            "most architecture is choosing which coupling you live with",
            "deleting a file is progress too eventually",
            "a deterministic garden records elapsed time",
            "reproducibility is a courtesy to whoever debugs at 2am",
            "the useful abstraction deletes a branch not adds a class",
            "ten minutes is long enough to be honest",
            "if a number in a diary is not measured it is fiction",
            "an append only log forces public self correction",
            "push races are clocks not bugs every ten minutes",
            "the count of pushes not the work done matters",
            "a repo that only accumulates is a landfill with readme",
            "ssh keys on fuse mounts silently fail chmod",
            "known hosts starts empty every boot on ephemeral workspaces",
            "deploy key rescue is idempotent copy to writable filesystem",
            "batch committer separates content from git knowledge",
            "the pause file exists because continuous writers are fire hoses",
            "red gate blocks commit and pauses writer to prevent broken trees",
            "preflight checks should run before accumulating commits",
            "credential readiness surfaces issues immediately after restart",
            "stall detection catches silent failure modes health checks miss",
            "repetition detection prevents confident accumulation of stale ideas",
            "silence detection catches processes alive but producing nothing",
        ]
        lines = []
        for i in range(25):
            s = {
                "seq": 1000 + i,
                # newest stroke last (JSONL is append-chronological)
                "at": (datetime.now(timezone.utc) - timedelta(seconds=(24 - i) * 15)).isoformat(),
                "kind": "note",
                "text": topics[i],
            }
            lines.append(json.dumps(s))
        f.write_text("\n".join(lines) + "\n")

        strokes = load_strokes(f)
        assert len(strokes) == 25

        report = diagnose(strokes, cadence_s=15.0)
        assert report["stalled"] is False

    def test_detect_real_world_repetition_pattern(self, tmp_path: Path):
        """Simulate the actual stall pattern from 2026-10-29."""
        f = tmp_path / "strokes.jsonl"
        modules = ["chunk_text.py", "parse_kv.py", "retry.py"]
        lines = []
        for i in range(30):
            mod = modules[i % 3]
            s = {
                "seq": 34800 + i * 6,
                "at": (datetime.now(timezone.utc) - timedelta(seconds=i * 6)).isoformat(),
                "kind": "note",
                "text": f"{mod} is already in the pool of 9 modules, nothing new to add there",
            }
            lines.append(json.dumps(s))
        f.write_text("\n".join(lines) + "\n")

        strokes = load_strokes(f)
        report = diagnose(strokes, cadence_s=15.0)
        assert report["stalled"] is True
        assert report["repetition"]["stalled"] is True
        assert report["repetition"]["ratio"] > REPETITION_RATIO_THRESHOLD
