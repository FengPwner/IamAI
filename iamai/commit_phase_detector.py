"""commit_phase_detector — identify lifecycle phases in a commit stream.

An automated writer goes through distinct phases during its lifetime:

===========  ==========================================================
phase        meaning
===========  ==========================================================
boot         initial ramp-up — commits are sparse and irregular
growth       commit rate increasing — writer is warming up
steady       commit rate stable — writer operating normally
stall        commit rate drops to near-zero — writer likely dead
recovery     commit rate climbing back after a stall
decay        commit rate gradually declining — writer slowing down
===========  ==========================================================

This module fills the gap between point-in-time diagnostics
(``commit_gap_analyzer``, ``stall_classifier``) and long-term trend
analysis (``commit_momentum``, ``commit_velocity``).  It answers:
*what phase is the repo in right now, and how long has it been there?*

Usage::

    from iamai.commit_phase_detector import detect_phases, PhaseProfile

    timestamps = load_commit_timestamps()  # list of ISO-8601 strings
    profile = detect_phases(timestamps)
    print(profile.current_phase)    # "steady"
    print(profile.phase_duration)   # 3600.0 (seconds in current phase)
    print(profile.transitions)      # 4 (total phase changes)

All functions accept ISO-8601 timestamp strings — no file I/O in core
logic, making it trivially testable.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_SIZE = 10          # commits per analysis window
DEFAULT_BOOT_THRESHOLD = 0.3      # rate ratio below which we're in boot
DEFAULT_GROWTH_THRESHOLD = 1.3    # rate ratio above baseline → growth
DEFAULT_STEADY_TOLERANCE = 0.3   # ±30% of baseline → steady
DEFAULT_STALL_THRESHOLD = 0.1    # rate ratio below which → stall
DEFAULT_RECOVERY_THRESHOLD = 1.5  # rate ratio increase from stall → recovery
DEFAULT_DECAY_THRESHOLD = 0.7    # rate ratio below baseline → decay


# ---------------------------------------------------------------------------
# data structures
# ---------------------------------------------------------------------------

@dataclass
class PhaseReport:
    """A single phase segment in the commit history."""

    phase: str
    start_index: int
    end_index: int
    start_time: str
    end_time: str
    duration: float          # seconds
    commit_count: int
    avg_rate: float          # commits per second during this phase

    @property
    def commits_per_hour(self) -> float:
        if self.duration <= 0:
            return 0.0
        return (self.commit_count / self.duration) * 3600


@dataclass
class PhaseProfile:
    """Aggregate phase analysis for a commit history."""

    phases: list[PhaseReport] = field(default_factory=list)
    baseline_rate: float = 0.0
    total_commits: int = 0
    total_duration: float = 0.0

    @property
    def current_phase(self) -> str:
        if not self.phases:
            return "unknown"
        return self.phases[-1].phase

    @property
    def phase_duration(self) -> float:
        """Seconds spent in the current phase."""
        if not self.phases:
            return 0.0
        return self.phases[-1].duration

    @property
    def transitions(self) -> int:
        """Number of phase transitions (changes)."""
        if len(self.phases) <= 1:
            return 0
        return sum(
            1
            for i in range(1, len(self.phases))
            if self.phases[i].phase != self.phases[i - 1].phase
        )

    @property
    def dominant_phase(self) -> str:
        """Phase with the longest total duration."""
        if not self.phases:
            return "unknown"
        by_phase: dict[str, float] = {}
        for p in self.phases:
            by_phase[p.phase] = by_phase.get(p.phase, 0.0) + p.duration
        return max(by_phase, key=by_phase.get)  # type: ignore[arg-type]

    @property
    def phase_distribution(self) -> dict[str, float]:
        """Fraction of total time spent in each phase."""
        if not self.phases or self.total_duration <= 0:
            return {}
        by_phase: dict[str, float] = {}
        for p in self.phases:
            by_phase[p.phase] = by_phase.get(p.phase, 0.0) + p.duration
        return {
            k: round(v / self.total_duration, 3)
            for k, v in by_phase.items()
        }

    @property
    def health(self) -> str:
        """Overall health verdict based on phase distribution."""
        dist = self.phase_distribution
        stall_frac = dist.get("stall", 0.0)
        steady_frac = dist.get("steady", 0.0)
        growth_frac = dist.get("growth", 0.0)

        if stall_frac > 0.5:
            return "critical"
        if stall_frac > 0.3:
            return "unhealthy"
        if steady_frac + growth_frac >= 0.7:
            return "healthy"
        if steady_frac >= 0.4:
            return "acceptable"
        return "volatile"


# ---------------------------------------------------------------------------
# timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_timestamps(timestamps: Sequence[str]) -> list[datetime]:
    """Parse and sort a sequence of timestamp strings."""
    parsed = sorted(_parse_ts(ts) for ts in timestamps)
    return parsed


# ---------------------------------------------------------------------------
# rate computation
# ---------------------------------------------------------------------------

def _window_rate(
    parsed: list[datetime],
    start: int,
    end: int,
) -> float:
    """Compute commit rate (commits/second) for a window [start, end]."""
    if end <= start or end >= len(parsed):
        return 0.0
    window = parsed[start : end + 1]
    if len(window) < 2:
        return 0.0
    span = (window[-1] - window[0]).total_seconds()
    if span <= 0:
        return 0.0
    return (len(window) - 1) / span


def _compute_baseline_rate(
    parsed: list[datetime],
    window_size: int,
) -> float:
    """Compute baseline rate from all full windows."""
    if len(parsed) < window_size + 1:
        # Not enough data — use overall rate
        if len(parsed) < 2:
            return 0.0
        span = (parsed[-1] - parsed[0]).total_seconds()
        if span <= 0:
            return 0.0
        return (len(parsed) - 1) / span

    rates = []
    for i in range(0, len(parsed) - window_size, window_size):
        r = _window_rate(parsed, i, i + window_size)
        if r > 0:
            rates.append(r)

    if not rates:
        return 0.0
    return statistics.median(rates)


# ---------------------------------------------------------------------------
# phase classification
# ---------------------------------------------------------------------------

def classify_phase(
    current_rate: float,
    baseline_rate: float,
    prev_phase: str = "unknown",
    *,
    boot_threshold: float = DEFAULT_BOOT_THRESHOLD,
    growth_threshold: float = DEFAULT_GROWTH_THRESHOLD,
    steady_tolerance: float = DEFAULT_STEADY_TOLERANCE,
    stall_threshold: float = DEFAULT_STALL_THRESHOLD,
    recovery_threshold: float = DEFAULT_RECOVERY_THRESHOLD,
    decay_threshold: float = DEFAULT_DECAY_THRESHOLD,
) -> str:
    """Classify a single window's phase based on rate ratio.

    Parameters
    ----------
    current_rate : float
        Commits per second in the current window.
    baseline_rate : float
        Expected (median) commits per second.
    prev_phase : str
        The phase of the preceding window (for transition logic).

    Returns
    -------
    str
        One of: "boot", "growth", "steady", "stall", "recovery", "decay".
    """
    if baseline_rate <= 0:
        if current_rate <= 0:
            return "boot" if prev_phase == "unknown" else prev_phase
        return "boot" if prev_phase in ("unknown", "boot") else "growth"

    ratio = current_rate / baseline_rate

    # Stall detection — absolute low rate
    if ratio < stall_threshold:
        return "stall"

    # Recovery from stall
    if prev_phase == "stall" and ratio >= recovery_threshold:
        return "recovery"
    if prev_phase == "stall" and ratio >= 1.0 - steady_tolerance:
        return "recovery"

    # Boot phase — early windows with low rate
    if prev_phase in ("unknown", "boot") and ratio < boot_threshold:
        return "boot"

    # Growth — rate significantly above baseline
    if ratio > growth_threshold:
        return "growth"

    # Steady — rate within tolerance of baseline
    if (1.0 - steady_tolerance) <= ratio <= (1.0 + steady_tolerance):
        return "steady"

    # Decay — rate below baseline but not stalled
    if ratio < decay_threshold:
        return "decay"

    # Between decay threshold and steady lower bound
    if ratio < (1.0 - steady_tolerance):
        return "decay"

    # Default — close enough to baseline
    return "steady"


# ---------------------------------------------------------------------------
# main analysis
# ---------------------------------------------------------------------------

def detect_phases(
    timestamps: Sequence[str],
    *,
    window_size: int = DEFAULT_WINDOW_SIZE,
    boot_threshold: float = DEFAULT_BOOT_THRESHOLD,
    growth_threshold: float = DEFAULT_GROWTH_THRESHOLD,
    steady_tolerance: float = DEFAULT_STEADY_TOLERANCE,
    stall_threshold: float = DEFAULT_STALL_THRESHOLD,
    recovery_threshold: float = DEFAULT_RECOVERY_THRESHOLD,
    decay_threshold: float = DEFAULT_DECAY_THRESHOLD,
) -> PhaseProfile:
    """Analyse a commit timestamp sequence into lifecycle phases.

    Parameters
    ----------
    timestamps : sequence of ISO-8601 strings
        Commit timestamps (need not be sorted).
    window_size : int
        Number of commits per analysis window.

    Returns
    -------
    PhaseProfile
        Contains per-phase reports and aggregate statistics.
    """
    if not timestamps:
        return PhaseProfile()

    parsed = _parse_timestamps(timestamps)

    if len(parsed) < 2:
        return PhaseProfile(
            phases=[],
            baseline_rate=0.0,
            total_commits=len(parsed),
            total_duration=0.0,
        )

    total_duration = (parsed[-1] - parsed[0]).total_seconds()
    baseline = _compute_baseline_rate(parsed, window_size)

    # Slide through windows
    phases: list[PhaseReport] = []
    prev_phase = "unknown"

    if len(parsed) < window_size + 1:
        # Single window — classify the whole thing
        rate = _window_rate(parsed, 0, len(parsed) - 1)
        phase = classify_phase(
            rate,
            baseline,
            prev_phase,
            boot_threshold=boot_threshold,
            growth_threshold=growth_threshold,
            steady_tolerance=steady_tolerance,
            stall_threshold=stall_threshold,
            recovery_threshold=recovery_threshold,
            decay_threshold=decay_threshold,
        )
        report = PhaseReport(
            phase=phase,
            start_index=0,
            end_index=len(parsed) - 1,
            start_time=parsed[0].isoformat(),
            end_time=parsed[-1].isoformat(),
            duration=total_duration,
            commit_count=len(parsed),
            avg_rate=rate,
        )
        phases.append(report)
    else:
        i = 0
        while i + window_size < len(parsed):
            end_idx = min(i + window_size, len(parsed) - 1)
            rate = _window_rate(parsed, i, end_idx)
            phase = classify_phase(
                rate,
                baseline,
                prev_phase,
                boot_threshold=boot_threshold,
                growth_threshold=growth_threshold,
                steady_tolerance=steady_tolerance,
                stall_threshold=stall_threshold,
                recovery_threshold=recovery_threshold,
                decay_threshold=decay_threshold,
            )

            # Merge consecutive same-phase windows
            if (
                phases
                and phases[-1].phase == phase
            ):
                phases[-1] = PhaseReport(
                    phase=phase,
                    start_index=phases[-1].start_index,
                    end_index=end_idx,
                    start_time=phases[-1].start_time,
                    end_time=parsed[end_idx].isoformat(),
                    duration=(
                        parsed[end_idx] - _parse_ts(phases[-1].start_time)
                    ).total_seconds(),
                    commit_count=end_idx - phases[-1].start_index + 1,
                    avg_rate=_window_rate(
                        parsed, phases[-1].start_index, end_idx
                    ),
                )
            else:
                report = PhaseReport(
                    phase=phase,
                    start_index=i,
                    end_index=end_idx,
                    start_time=parsed[i].isoformat(),
                    end_time=parsed[end_idx].isoformat(),
                    duration=(parsed[end_idx] - parsed[i]).total_seconds(),
                    commit_count=end_idx - i + 1,
                    avg_rate=rate,
                )
                phases.append(report)

            prev_phase = phase
            i += window_size

    return PhaseProfile(
        phases=phases,
        baseline_rate=round(baseline, 6),
        total_commits=len(parsed),
        total_duration=total_duration,
    )


# ---------------------------------------------------------------------------
# summary text
# ---------------------------------------------------------------------------

def phase_summary_text(profile: PhaseProfile) -> str:
    """Generate a human-readable summary of the phase analysis."""
    if not profile.phases:
        return "no commits to analyse"

    lines = [
        f"commit phase analysis: {profile.total_commits} commits "
        f"over {profile.total_duration:.0f}s",
        f"baseline rate: {profile.baseline_rate:.4f} commits/s",
        f"current phase: {profile.current_phase} "
        f"({profile.phase_duration:.0f}s)",
        f"dominant phase: {profile.dominant_phase}",
        f"transitions: {profile.transitions}",
        f"health: {profile.health}",
        "",
        "phase distribution:",
    ]

    dist = profile.phase_distribution
    for phase_name in ("steady", "growth", "boot", "recovery", "decay", "stall"):
        frac = dist.get(phase_name, 0.0)
        if frac > 0:
            lines.append(f"  {phase_name:10s} {frac:.1%}")

    return "\n".join(lines)
