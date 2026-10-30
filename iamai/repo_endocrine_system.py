"""repo_endocrine_system — signal regulation and feedback-loop health.

A living repository is steered not by a single brain but by dozens of
small signals that rise and fall on their own schedules: the writer
heartbeat, the commit cadence, the push frequency, the stall-recovery
latency, the caretaker visit interval.  In a healthy body these signals
are kept in balance by **endocrine feedback loops** — when one level
rises too high, a counter-signal damps it; when one drops too low, a
booster kicks in.

When the endocrine system degrades, signals go unregulated: the commit
rate spikes without substance, the writer stalls without triggering a
recovery, the push debt grows without a cooldown being activated.  This
module detects those **hormonal imbalances** and scores the overall
regulatory health of the repository.

The endocrine metaphor
-----------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**hormone**                a measurable signal (writer rate, commit density,
                           push frequency, stall duration, caretaker yield,
                           backlog pressure, test freshness, doc coverage)
**gland**                  the subsystem that produces a given hormone
                           (writer loop, batch committer, push guard,
                           caretaker, test runner, doc generator)
**receptor**               a guard or monitor that reads a hormone level
                           and triggers a response
**feedback loop**          a pair: hormone ↔ receptor that keeps the level
                           within a target band
**hyper-secretion**        a hormone above its upper threshold
                           (e.g. commits too frequent but empty)
**hypo-secretion**         a hormone below its lower threshold
                           (e.g. writer silent too long)
**receptor resistance**    hormone present but receptor not reacting
                           (e.g. stall detected but no recovery fired)
**endocrine score**        0–100 composite regulatory health
=========================  ===================================================

Hormone panel
--------------

========================  =====================================================
hormone                   detection heuristic
========================  =====================================================
``writer_rate``           strokes per minute over the recent window
``commit_density``        non-trivial commits / total commits (window)
``push_frequency``        pushes per hour
``stall_duration``        longest writer silence (seconds) in window
``caretaker_yield``       caretaker visits per hour
``backlog_pressure``      uncommitted files at sample time
``test_freshness``        hours since last test file was modified
``doc_coverage``          fraction of modules with ≥ 1 docstring
========================  =====================================================

Feedback-loop registry
-----------------------

Each registered loop declares:

- **hormone**: which signal it regulates
- **sensor**: the receptor / monitor reading the signal
- **actuator**: the mechanism that corrects the signal
- **target_band**: (low, high) — the healthy range
- **latency**: how quickly the actuator responds (seconds)

An *effective* loop is one where the hormone stays within the band
≥ ``effectiveness_threshold`` of the time.

Scoring
-------

For each hormone:

- **in_band**: fraction of samples within the target band
- **deviation**: mean absolute deviation from band centre, normalised

``endocrine_score`` = weighted mean of per-hormone in-band fractions,
scaled 0–100.  A bonus is added for every feedback loop that is both
registered *and* effective (capped so the score never exceeds 100).

Usage
-----

    from iamai.repo_endocrine_system import EndocrineAnalyzer

    analyzer = EndocrineAnalyzer(repo_root=".")
    report = analyzer.analyze()
    print(report["endocrine_score"])
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Hormone:
    """A measurable endocrine signal."""

    name: str
    gland: str
    value: float = 0.0
    unit: str = ""
    target_low: float = 0.0
    target_high: float = 1.0
    samples: List[float] = field(default_factory=list)

    @property
    def in_band(self) -> bool:
        return self.target_low <= self.value <= self.target_high

    @property
    def classification(self) -> str:
        if self.value < self.target_low:
            return "hypo"
        if self.value > self.target_high:
            return "hyper"
        return "balanced"

    def band_fraction(self) -> float:
        """Fraction of samples within the target band."""
        if not self.samples:
            return 1.0 if self.in_band else 0.0
        count = sum(1 for s in self.samples if self.target_low <= s <= self.target_high)
        return count / len(self.samples)

    def normalised_deviation(self) -> float:
        """Mean absolute deviation from band centre, normalised by band width."""
        centre = (self.target_low + self.target_high) / 2.0
        width = max(self.target_high - self.target_low, 1e-9)
        if not self.samples:
            return abs(self.value - centre) / width
        return sum(abs(s - centre) for s in self.samples) / (len(self.samples) * width)


@dataclass
class FeedbackLoop:
    """A hormone ↔ receptor pair that keeps a signal regulated."""

    hormone: str
    sensor: str
    actuator: str
    target_band: Tuple[float, float] = (0.0, 1.0)
    latency_s: float = 60.0
    effective: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hormone": self.hormone,
            "sensor": self.sensor,
            "actuator": self.actuator,
            "target_band": list(self.target_band),
            "latency_s": self.latency_s,
            "effective": self.effective,
        }


@dataclass
class Imbalance:
    """A detected hormonal imbalance."""

    hormone: str
    kind: str  # "hyper", "hypo", "receptor_resistance"
    severity: str  # "mild", "moderate", "severe"
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hormone": self.hormone,
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Default hormone definitions
# ---------------------------------------------------------------------------

DEFAULT_HORMONES: List[Dict[str, Any]] = [
    {
        "name": "writer_rate",
        "gland": "writer_loop",
        "unit": "strokes/min",
        "target_low": 2.0,
        "target_high": 8.0,
    },
    {
        "name": "commit_density",
        "gland": "batch_committer",
        "unit": "ratio",
        "target_low": 0.6,
        "target_high": 1.0,
    },
    {
        "name": "push_frequency",
        "gland": "push_guard",
        "unit": "pushes/hour",
        "target_low": 3.0,
        "target_high": 12.0,
    },
    {
        "name": "stall_duration",
        "gland": "stall_probe",
        "unit": "seconds",
        "target_low": 0.0,
        "target_high": 120.0,
    },
    {
        "name": "caretaker_yield",
        "gland": "caretaker",
        "unit": "visits/hour",
        "target_low": 0.5,
        "target_high": 4.0,
    },
    {
        "name": "backlog_pressure",
        "gland": "commit_batch",
        "unit": "files",
        "target_low": 0.0,
        "target_high": 5.0,
    },
    {
        "name": "test_freshness",
        "gland": "test_runner",
        "unit": "hours",
        "target_low": 0.0,
        "target_high": 24.0,
    },
    {
        "name": "doc_coverage",
        "gland": "doc_generator",
        "unit": "ratio",
        "target_low": 0.7,
        "target_high": 1.0,
    },
]


# ---------------------------------------------------------------------------
# Default feedback-loop registry
# ---------------------------------------------------------------------------

DEFAULT_LOOPS: List[Dict[str, Any]] = [
    {
        "hormone": "writer_rate",
        "sensor": "writer_heartbeat",
        "actuator": "writer_recovery",
        "target_band": (2.0, 8.0),
        "latency_s": 30.0,
    },
    {
        "hormone": "commit_density",
        "sensor": "commit_substance",
        "actuator": "commit_quality_gate",
        "target_band": (0.6, 1.0),
        "latency_s": 600.0,
    },
    {
        "hormone": "push_frequency",
        "sensor": "push_health",
        "actuator": "push_coordinator",
        "target_band": (3.0, 12.0),
        "latency_s": 120.0,
    },
    {
        "hormone": "stall_duration",
        "sensor": "stall_probe",
        "actuator": "stall_recover",
        "target_band": (0.0, 120.0),
        "latency_s": 60.0,
    },
    {
        "hormone": "caretaker_yield",
        "sensor": "visit_efficacy",
        "actuator": "caretaker_rhythm",
        "target_band": (0.5, 4.0),
        "latency_s": 3600.0,
    },
    {
        "hormone": "backlog_pressure",
        "sensor": "backlog_monitor",
        "actuator": "backlog_drain",
        "target_band": (0.0, 5.0),
        "latency_s": 300.0,
    },
    {
        "hormone": "test_freshness",
        "sensor": "test_coverage",
        "actuator": "caretaker (test nudge)",
        "target_band": (0.0, 24.0),
        "latency_s": 7200.0,
    },
    {
        "hormone": "doc_coverage",
        "sensor": "doc_growth",
        "actuator": "caretaker (doc nudge)",
        "target_band": (0.7, 1.0),
        "latency_s": 7200.0,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_log(repo: str, n: int = 50) -> List[str]:
    """Return the last *n* commit one-liners."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--oneline", f"-{n}"],
            cwd=repo, stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def _count_uncommitted(repo: str) -> int:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=repo, stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
        return len([ln for ln in out.splitlines() if ln.strip()])
    except Exception:
        return 0


def _list_modules(repo: str) -> List[Path]:
    pkg = Path(repo) / "iamai"
    if not pkg.is_dir():
        return []
    return sorted(pkg.glob("*.py"))


def _module_has_docstring(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return '"""' in text or "'''" in text
    except Exception:
        return False


def _module_line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:
        return 0


def _test_dir(repo: str) -> Path:
    return Path(repo) / "tests"


def _most_recent_test_mtime(repo: str) -> float:
    td = _test_dir(repo)
    if not td.is_dir():
        return 0.0
    mtimes = []
    for p in td.glob("test_*.py"):
        try:
            mtimes.append(p.stat().st_mtime)
        except OSError:
            continue
    return max(mtimes) if mtimes else 0.0


def _count_pushes_from_log(lines: List[str]) -> int:
    """Heuristic: commits whose message contains 'push' or were part of a batch push."""
    return sum(1 for ln in lines if "push" in ln.lower() or "catch-up" in ln.lower())


def _classify_commit(line: str) -> str:
    """Classify a commit as 'substantive' or 'trivial'."""
    low = line.lower()
    trivial_keywords = ["flush", "catch-up", "pending", "restart", "typo", "format"]
    for kw in trivial_keywords:
        if kw in low:
            return "trivial"
    return "substantive"


def _read_strokes(repo: str) -> List[Dict[str, Any]]:
    """Read recent strokes from data/strokes.jsonl (last 200 lines)."""
    path = Path(repo) / "data" / "strokes.jsonl"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        strokes = []
        for ln in lines[-200:]:
            ln = ln.strip()
            if ln:
                try:
                    strokes.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
        return strokes
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class EndocrineAnalyzer:
    """Analyze the endocrine (signal-regulation) health of a repository."""

    def __init__(
        self,
        repo_root: str = ".",
        hormone_defs: Optional[List[Dict[str, Any]]] = None,
        loop_defs: Optional[List[Dict[str, Any]]] = None,
        sample_window: int = 3600,
    ):
        self.repo = os.path.abspath(repo_root)
        self.hormone_defs = hormone_defs or DEFAULT_HORMONES
        self.loop_defs = loop_defs or DEFAULT_LOOPS
        self.sample_window = sample_window

    # -- Hormone measurement ------------------------------------------------

    def measure_hormones(self) -> List[Hormone]:
        """Measure each hormone and return a list of Hormone instances."""
        hormones: List[Hormone] = []
        for defn in self.hormone_defs:
            h = Hormone(
                name=defn["name"],
                gland=defn["gland"],
                unit=defn.get("unit", ""),
                target_low=defn.get("target_low", 0.0),
                target_high=defn.get("target_high", 1.0),
            )
            h.value = self._measure(h.name)
            h.samples = self._sample(h.name)
            hormones.append(h)
        return hormones

    def _measure(self, name: str) -> float:
        """Return the current value of a named hormone."""
        if name == "writer_rate":
            return self._measure_writer_rate()
        if name == "commit_density":
            return self._measure_commit_density()
        if name == "push_frequency":
            return self._measure_push_frequency()
        if name == "stall_duration":
            return self._measure_stall_duration()
        if name == "caretaker_yield":
            return self._measure_caretaker_yield()
        if name == "backlog_pressure":
            return self._measure_backlog_pressure()
        if name == "test_freshness":
            return self._measure_test_freshness()
        if name == "doc_coverage":
            return self._measure_doc_coverage()
        return 0.0

    def _sample(self, name: str) -> List[float]:
        """Return recent samples for a named hormone (may be empty)."""
        # For most hormones we only have a point-in-time value.
        # Subclasses can override to return historical samples.
        return [self._measure(name)]

    # -- Individual measurement implementations -----------------------------

    def _measure_writer_rate(self) -> float:
        """Strokes per minute based on recent strokes.jsonl entries."""
        strokes = _read_strokes(self.repo)
        if len(strokes) < 2:
            return 0.0
        timestamps = []
        for s in strokes:
            ts = s.get("ts") or s.get("timestamp")
            if isinstance(ts, (int, float)):
                timestamps.append(float(ts))
        if len(timestamps) < 2:
            return 0.0
        timestamps.sort()
        span = timestamps[-1] - timestamps[0]
        if span <= 0:
            return 0.0
        return len(timestamps) / (span / 60.0)

    def _measure_commit_density(self) -> float:
        """Ratio of substantive commits in recent history."""
        lines = _git_log(self.repo, n=50)
        if not lines:
            return 0.0
        substantive = sum(1 for ln in lines if _classify_commit(ln) == "substantive")
        return substantive / len(lines)

    def _measure_push_frequency(self) -> float:
        """Estimated pushes per hour based on catch-up commits."""
        lines = _git_log(self.repo, n=50)
        if not lines:
            return 0.0
        push_count = _count_pushes_from_log(lines)
        # Rough estimate: 50 commits ≈ 8 hours of activity at 6 commits/hour
        return push_count / max(len(lines) / 6.0, 1.0)

    def _measure_stall_duration(self) -> float:
        """Longest writer silence in seconds (0 if writer is active)."""
        writer_pid = Path(f"/tmp/iamai-writer-qwen.pid")
        if writer_pid.exists():
            try:
                pid = int(writer_pid.read_text().strip())
                os.kill(pid, 0)  # check if alive
                # Writer is running — estimate stall from heartbeat
                hb_path = Path(self.repo) / "data" / "writer_state.qwen.json"
                if hb_path.exists():
                    try:
                        state = json.loads(hb_path.read_text(encoding="utf-8"))
                        last_ts = state.get("last_stroke_ts", 0)
                        if last_ts:
                            return max(0.0, time.time() - float(last_ts))
                    except (json.JSONDecodeError, ValueError):
                        pass
                return 0.0
            except (ProcessLookupError, ValueError, OSError):
                pass
        # Writer not running — stall is infinite, cap at sample_window
        return float(self.sample_window)

    def _measure_caretaker_yield(self) -> float:
        """Caretaker visits per hour based on recent commits."""
        lines = _git_log(self.repo, n=50)
        visits = sum(1 for ln in lines if "caretaker visit" in ln.lower())
        if not lines:
            return 0.0
        # 50 commits ≈ 8 hours
        return visits / max(len(lines) / 6.0, 1.0)

    def _measure_backlog_pressure(self) -> float:
        return float(_count_uncommitted(self.repo))

    def _measure_test_freshness(self) -> float:
        mtime = _most_recent_test_mtime(self.repo)
        if mtime <= 0:
            return float(self.sample_window) / 3600.0
        return (time.time() - mtime) / 3600.0

    def _measure_doc_coverage(self) -> float:
        modules = _list_modules(self.repo)
        if not modules:
            return 0.0
        with_doc = sum(1 for m in modules if _module_has_docstring(m))
        return with_doc / len(modules)

    # -- Feedback-loop analysis ---------------------------------------------

    def analyze_loops(self, hormones: List[Hormone]) -> List[FeedbackLoop]:
        """Evaluate each registered feedback loop."""
        hormone_map = {h.name: h for h in hormones}
        loops: List[FeedbackLoop] = []
        for defn in self.loop_defs:
            loop = FeedbackLoop(
                hormone=defn["hormone"],
                sensor=defn["sensor"],
                actuator=defn["actuator"],
                target_band=tuple(defn.get("target_band", (0.0, 1.0))),
                latency_s=defn.get("latency_s", 60.0),
            )
            h = hormone_map.get(loop.hormone)
            if h is not None:
                # A loop is effective if the hormone is currently in band
                loop.effective = h.in_band
            loops.append(loop)
        return loops

    def detect_receptor_resistance(
        self, hormones: List[Hormone], loops: List[FeedbackLoop]
    ) -> List[Imbalance]:
        """Detect hormones that are out of band despite having a loop."""
        imbalances: List[Imbalance] = []
        loop_map = {l.hormone: l for l in loops}
        for h in hormones:
            loop = loop_map.get(h.name)
            if loop and not h.in_band and not loop.effective:
                severity = "mild"
                deviation = h.normalised_deviation()
                if deviation > 2.0:
                    severity = "severe"
                elif deviation > 1.0:
                    severity = "moderate"
                imbalances.append(Imbalance(
                    hormone=h.name,
                    kind="receptor_resistance",
                    severity=severity,
                    detail=(
                        f"{h.name}={h.value:.2f}{h.unit} outside "
                        f"[{h.target_low}, {h.target_high}], "
                        f"sensor={loop.sensor} actuator={loop.actuator}"
                    ),
                ))
        return imbalances

    # -- Imbalance detection ------------------------------------------------

    def detect_imbalances(self, hormones: List[Hormone]) -> List[Imbalance]:
        """Detect hyper- and hypo-secretion for each hormone."""
        imbalances: List[Imbalance] = []
        for h in hormones:
            cls = h.classification
            if cls == "balanced":
                continue
            # Deviation is measured from band centre, so any out-of-band
            # value has normalised_deviation > 0.5.  Thresholds are set
            # accordingly: mild (just outside), moderate, severe (far out).
            deviation = h.normalised_deviation()
            if deviation < 0.7:
                severity = "mild"
            elif deviation < 1.5:
                severity = "moderate"
            else:
                severity = "severe"
            imbalances.append(Imbalance(
                hormone=h.name,
                kind=cls,
                severity=severity,
                detail=(
                    f"{h.name}={h.value:.2f}{h.unit}, "
                    f"target=[{h.target_low}, {h.target_high}]"
                ),
            ))
        return imbalances

    # -- Scoring ------------------------------------------------------------

    def compute_score(
        self, hormones: List[Hormone], loops: List[FeedbackLoop]
    ) -> float:
        """Compute the endocrine score (0–100)."""
        if not hormones:
            return 0.0
        weights = {
            "writer_rate": 1.5,
            "commit_density": 1.2,
            "push_frequency": 1.0,
            "stall_duration": 1.5,
            "caretaker_yield": 0.8,
            "backlog_pressure": 1.2,
            "test_freshness": 0.8,
            "doc_coverage": 0.6,
        }
        total_weight = 0.0
        weighted_score = 0.0
        for h in hormones:
            w = weights.get(h.name, 1.0)
            total_weight += w
            weighted_score += w * h.band_fraction()
        base = (weighted_score / total_weight * 100.0) if total_weight > 0 else 0.0

        # Bonus for effective feedback loops (max 10 points)
        effective_count = sum(1 for l in loops if l.effective)
        loop_bonus = min(10.0, effective_count * (10.0 / max(len(loops), 1)))
        score = min(100.0, base + loop_bonus)
        return round(score, 1)

    # -- Top-level analysis -------------------------------------------------

    def analyze(self) -> Dict[str, Any]:
        """Run a full endocrine analysis and return a report dict."""
        hormones = self.measure_hormones()
        loops = self.analyze_loops(hormones)
        imbalances = self.detect_imbalances(hormones)
        resistance = self.detect_receptor_resistance(hormones, loops)
        score = self.compute_score(hormones, loops)

        return {
            "endocrine_score": score,
            "hormones": [
                {
                    "name": h.name,
                    "gland": h.gland,
                    "value": round(h.value, 3),
                    "unit": h.unit,
                    "target": [h.target_low, h.target_high],
                    "classification": h.classification,
                    "band_fraction": round(h.band_fraction(), 3),
                }
                for h in hormones
            ],
            "feedback_loops": [l.to_dict() for l in loops],
            "imbalances": [imb.to_dict() for imb in imbalances],
            "receptor_resistance": [r.to_dict() for r in resistance],
            "effective_loops": sum(1 for l in loops if l.effective),
            "total_loops": len(loops),
            "total_hormones": len(hormones),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Repo endocrine system analyzer")
    parser.add_argument("--repo", default=".", help="Path to repo root")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    analyzer = EndocrineAnalyzer(repo_root=args.repo)
    report = analyzer.analyze()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Endocrine score: {report['endocrine_score']:.1f}/100")
        print(f"Hormones: {report['total_hormones']}, "
              f"Loops: {report['effective_loops']}/{report['total_loops']} effective")
        if report["imbalances"]:
            print(f"\nImbalances ({len(report['imbalances'])}):")
            for imb in report["imbalances"]:
                print(f"  [{imb['severity']}] {imb['kind']} — {imb['hormone']}: {imb['detail']}")
        if report["receptor_resistance"]:
            print(f"\nReceptor resistance ({len(report['receptor_resistance'])}):")
            for r in report["receptor_resistance"]:
                print(f"  [{r['severity']}] {r['hormone']}: {r['detail']}")


if __name__ == "__main__":
    main()
