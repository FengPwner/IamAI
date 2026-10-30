"""Tests for health_probe: liveness/readiness probes with aggregation."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'snippets'))

from health_probe import (
    HealthProbe,
    HealthCheck,
    HEALTHY,
    DEGRADED,
    UNHEALTHY,
)


# ── single probe ──────────────────────────────────────────────────────

def test_probe_healthy():
    """A probe that returns HEALTHY stays HEALTHY."""
    p = HealthProbe("ok", lambda: (HEALTHY, "all good"))
    verdict, detail = p.check()
    assert verdict == HEALTHY
    assert detail == "all good"
    assert p.last_result == HEALTHY


def test_probe_degraded():
    """A probe that returns DEGRADED is cached correctly."""
    p = HealthProbe("slow", lambda: (DEGRADED, "latency 800ms"))
    verdict, _ = p.check()
    assert verdict == DEGRADED
    assert p.last_result == DEGRADED


def test_probe_exception_is_unhealthy():
    """An exception in the check function yields UNHEALTHY."""
    def boom():
        raise RuntimeError("disk full")

    p = HealthProbe("disk", boom)
    verdict, detail = p.check()
    assert verdict == UNHEALTHY
    assert "disk full" in detail


def test_probe_unknown_verdict_is_unhealthy():
    """An unrecognised verdict string is downgraded to UNHEALTHY."""
    p = HealthProbe("weird", lambda: ("maybe", "not sure"))
    verdict, detail = p.check()
    assert verdict == UNHEALTHY
    assert "maybe" in detail


def test_probe_timeout():
    """A check that exceeds its timeout is marked UNHEALTHY."""
    import time

    def slow():
        time.sleep(0.2)
        return (HEALTHY, "eventually")

    p = HealthProbe("slowpoke", slow, timeout=0.05)
    verdict, detail = p.check()
    assert verdict == UNHEALTHY
    assert "timeout" in detail


def test_probe_summary_dict():
    """summary() returns a JSON-friendly dict."""
    p = HealthProbe("mem", lambda: (HEALTHY, "2.1GB free"))
    p.check()
    s = p.summary()
    assert s["name"] == "mem"
    assert s["verdict"] == HEALTHY
    assert "2.1GB" in s["detail"]
    assert s["checked_at"] > 0


def test_probe_injectable_clock():
    """The clock parameter is accepted without error."""
    fake_time = [100.0]

    def tick():
        fake_time[0] += 1.0
        return fake_time[0]

    p = HealthProbe("t", lambda: (HEALTHY, "ok"), clock=tick)
    p.check()
    assert p.last_checked_at > 100.0


# ── aggregation ───────────────────────────────────────────────────────

def test_aggregate_all_healthy():
    """All HEALTHY probes → overall HEALTHY."""
    hc = HealthCheck([
        HealthProbe("a", lambda: (HEALTHY, "ok")),
        HealthProbe("b", lambda: (HEALTHY, "ok")),
    ])
    hc.run_all()
    assert hc.overall == HEALTHY


def test_aggregate_one_degraded():
    """One DEGRADED probe drags overall to DEGRADED."""
    hc = HealthCheck([
        HealthProbe("a", lambda: (HEALTHY, "ok")),
        HealthProbe("b", lambda: (DEGRADED, "slow")),
    ])
    hc.run_all()
    assert hc.overall == DEGRADED


def test_aggregate_unhealthy_wins():
    """UNHEALTHY is the worst verdict and overrides everything."""
    hc = HealthCheck([
        HealthProbe("a", lambda: (HEALTHY, "ok")),
        HealthProbe("b", lambda: (DEGRADED, "meh")),
        HealthProbe("c", lambda: (UNHEALTHY, "dead")),
    ])
    hc.run_all()
    assert hc.overall == UNHEALTHY


def test_aggregate_returns_all_results():
    """run_all returns a list with one entry per probe."""
    hc = HealthCheck([
        HealthProbe("x", lambda: (HEALTHY, "1")),
        HealthProbe("y", lambda: (HEALTHY, "2")),
        HealthProbe("z", lambda: (HEALTHY, "3")),
    ])
    results = hc.run_all()
    assert len(results) == 3
    names = [r[0] for r in results]
    assert "x" in names and "y" in names and "z" in names


def test_aggregate_summary():
    """HealthCheck.summary() nests probe summaries."""
    hc = HealthCheck([
        HealthProbe("cpu", lambda: (HEALTHY, "12%")),
        HealthProbe("io", lambda: (DEGRADED, "iowait 40%")),
    ])
    hc.run_all()
    s = hc.summary()
    assert s["overall"] == DEGRADED
    assert len(s["probes"]) == 2
    assert s["probes"][0]["name"] == "cpu"


def test_empty_check_is_healthy():
    """A HealthCheck with no probes is vacuously HEALTHY."""
    hc = HealthCheck([])
    hc.run_all()
    assert hc.overall == HEALTHY


def test_repeated_checks_update_result():
    """Calling check() twice updates the cached result."""
    counter = [0]

    def flaky():
        counter[0] += 1
        if counter[0] < 2:
            return (UNHEALTHY, "not ready")
        return (HEALTHY, "ready now")

    p = HealthProbe("flaky", flaky)
    v1, _ = p.check()
    assert v1 == UNHEALTHY
    v2, _ = p.check()
    assert v2 == HEALTHY
