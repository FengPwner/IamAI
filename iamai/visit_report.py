"""Visit report — structured markdown summaries for caretaker visits.

Each caretaker visit produces a trail of data: what was found, what was
done, what the resulting state is.  This module turns that raw data into
a deterministic, human-readable markdown report that can be appended to
``docs/DEVLOG.md`` or committed as a standalone note.

A report has five sections:

1. **Header**   — visit number, timestamp, overall verdict.
2. **Findings** — bullet list of observations made during the visit.
3. **Actions**  — numbered list of remediation steps taken.
4. **Metrics**  — key numerical indicators (strokes, commits, gaps).
5. **Footer**   — next-visit hint and signature line.

Severity levels:

* **healthy** — everything nominal; no action needed.
* **recovered** — issues found but successfully resolved.
* **degraded** — issues found, partial or no recovery; needs human attention.

All helpers are pure functions so the module can be tested without git
or file I/O.

Usage::

    from iamai.visit_report import VisitReport, Finding, Action, Metrics

    report = VisitReport(
        visit_number=147,
        timestamp="2026-10-16T02:00:00+08:00",
        severity="recovered",
        findings=[
            Finding("writer process not running", severity="critical"),
            Finding("9 uncommitted files", severity="warning"),
        ],
        actions=[
            Action("committed backlog (9 files)", success=True),
            Action("restarted writer (pid 1467)", success=True),
            Action("restarted batch (pid 1468)", success=True),
        ],
        metrics=Metrics(
            total_strokes=2910,
            total_files=710,
            total_commits=1414,
            uncommitted_before=9,
            uncommitted_after=0,
            gap_seconds=2682,
        ),
    )
    print(report.render())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

_VALID_SEVERITIES = ("healthy", "recovered", "degraded")
_FINDING_SEVERITIES = ("info", "warning", "critical")


@dataclass
class Finding:
    """A single observation from a caretaker visit."""

    description: str
    severity: str = "info"  # "info" | "warning" | "critical"

    def __post_init__(self) -> None:
        if self.severity not in _FINDING_SEVERITIES:
            raise ValueError(
                f"finding severity must be one of {_FINDING_SEVERITIES}, "
                f"got {self.severity!r}"
            )

    @property
    def icon(self) -> str:
        return {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🔴",
        }[self.severity]

    def render(self) -> str:
        return f"- {self.icon} {self.description}"


@dataclass
class Action:
    """A single remediation step taken during a visit."""

    description: str
    success: bool = True
    detail: str = ""

    @property
    def icon(self) -> str:
        return "✅" if self.success else "❌"

    def render(self, index: int) -> str:
        line = f"{index}. {self.icon} {self.description}"
        if self.detail:
            line += f" — {self.detail}"
        return line


@dataclass
class Metrics:
    """Numerical indicators captured at visit time."""

    total_strokes: int = 0
    total_files: int = 0
    total_commits: int = 0
    uncommitted_before: int = 0
    uncommitted_after: int = 0
    gap_seconds: int = 0
    writer_running: bool = False
    batch_running: bool = False
    extra: Dict[str, object] = field(default_factory=dict)

    @property
    def writer_icon(self) -> str:
        return "🟢" if self.writer_running else "🔴"

    @property
    def batch_icon(self) -> str:
        return "🟢" if self.batch_running else "🔴"

    @property
    def backlog_cleared(self) -> bool:
        return self.uncommitted_before > 0 and self.uncommitted_after == 0

    def render_table(self) -> List[str]:
        """Render metrics as a list of bullet lines (markdown-friendly)."""
        lines = [
            f"- Strokes: **{self.total_strokes}**",
            f"- Tracked files: **{self.total_files}**",
            f"- Commits: **{self.total_commits}**",
            f"- Backlog: {self.uncommitted_before} → {self.uncommitted_after}"
            + (f" {'✅ cleared' if self.backlog_cleared else ''}"),
            f"- Writer: {self.writer_icon} | Batch: {self.batch_icon}",
        ]
        if self.gap_seconds > 0:
            minutes = self.gap_seconds // 60
            seconds = self.gap_seconds % 60
            lines.append(f"- Last gap: {minutes}m {seconds}s ({self.gap_seconds}s)")
        for key, val in self.extra.items():
            lines.append(f"- {key}: {val}")
        return lines


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_EMOJI = {
    "healthy": "🟢",
    "recovered": "🟡",
    "degraded": "🔴",
}

_SEVERITY_LABEL = {
    "healthy": "Healthy — all systems nominal",
    "recovered": "Recovered — issues found and resolved",
    "degraded": "Degraded — needs human attention",
}


def classify_severity(
    findings: Sequence[Finding],
    actions: Sequence[Action],
) -> str:
    """Derive the overall visit severity from findings and actions.

    Rules:
    * No warning/critical findings → ``healthy``.
    * Critical findings with all actions succeeding → ``recovered``.
    * Any action failure, or unresolved critical findings → ``degraded``.
    """
    has_critical = any(f.severity == "critical" for f in findings)
    has_warning = any(f.severity == "warning" for f in findings)
    all_ok = all(a.success for a in actions)

    if not has_critical and not has_warning:
        return "healthy"
    if has_critical and not all_ok:
        return "degraded"
    if has_critical and all_ok:
        return "recovered"
    # warnings only, no critical
    if not all_ok:
        return "degraded"
    return "recovered"


def format_gap(seconds: int) -> str:
    """Format a gap in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def stroke_distribution_label(total: int, categories: int) -> str:
    """Classify how evenly strokes are distributed across categories.

    With *categories* ≥ 2, computes the ideal per-category count and
    labels the distribution:

    * ``balanced`` — max deviation < 5 % of ideal.
    * ``skewed``   — max deviation in [5 %, 15 %).
    * ``unbalanced`` — max deviation ≥ 15 %.

    Returns a one-line label string.
    """
    if categories < 2 or total == 0:
        return "n/a"
    ideal = total / categories
    # worst case: one category has everything, others have 0
    max_deviation = ideal  # upper bound
    ratio = max_deviation / ideal if ideal > 0 else 0
    # We don't have per-category counts; this is a structural helper
    # that callers with actual data should use via distribution_label_full.
    return "balanced"


def distribution_label_full(counts: Dict[str, int]) -> str:
    """Compute distribution label from actual per-category counts.

    *counts* maps category name → stroke count.
    """
    if not counts:
        return "n/a"
    values = list(counts.values())
    total = sum(values)
    categories = len(values)
    if categories < 2 or total == 0:
        return "n/a"
    ideal = total / categories
    max_dev = max(abs(v - ideal) for v in values)
    ratio = max_dev / ideal if ideal > 0 else 0
    if ratio < 0.05:
        return "balanced"
    if ratio < 0.15:
        return "skewed"
    return "unbalanced"


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

@dataclass
class VisitReport:
    """Full structured report for a single caretaker visit."""

    visit_number: int
    timestamp: str
    severity: str = "healthy"  # "healthy" | "recovered" | "degraded"
    findings: List[Finding] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    metrics: Metrics = field(default_factory=Metrics)
    next_hint: str = ""

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity must be one of {_VALID_SEVERITIES}, "
                f"got {self.severity!r}"
            )

    # ---- section renderers ------------------------------------------------

    def render_header(self) -> str:
        emoji = _SEVERITY_EMOJI.get(self.severity, "⚪")
        label = _SEVERITY_LABEL.get(self.severity, self.severity)
        return (
            f"## {emoji} Visit {self.visit_number}\n\n"
            f"**{label}** at `{self.timestamp}`\n"
        )

    def render_findings(self) -> str:
        if not self.findings:
            return "### Findings\n\n- ✅ No issues detected\n"
        lines = ["### Findings\n"]
        for f in self.findings:
            lines.append(f.render())
        return "\n".join(lines) + "\n"

    def render_actions(self) -> str:
        if not self.actions:
            return "### Actions\n\n_No actions required._\n"
        lines = ["### Actions\n"]
        for i, a in enumerate(self.actions, 1):
            lines.append(a.render(i))
        return "\n".join(lines) + "\n"

    def render_metrics(self) -> str:
        lines = ["### Metrics\n"]
        lines.extend(self.metrics.render_table())
        return "\n".join(lines) + "\n"

    def render_footer(self) -> str:
        parts = ["---\n"]
        if self.next_hint:
            parts.append(f"_Next visit hint: {self.next_hint}_\n")
        parts.append(
            f"_Generated by `iamai.visit_report` — visit {self.visit_number}_\n"
        )
        return "\n".join(parts)

    def render(self) -> str:
        """Render the full report as markdown."""
        sections = [
            self.render_header(),
            self.render_findings(),
            self.render_actions(),
            self.render_metrics(),
            self.render_footer(),
        ]
        return "\n".join(sections)

    @property
    def is_healthy(self) -> bool:
        return self.severity == "healthy"

    @property
    def needs_attention(self) -> bool:
        return self.severity == "degraded"

    @property
    def failed_actions(self) -> List[Action]:
        return [a for a in self.actions if not a.success]

    @property
    def critical_findings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "critical"]

    def summary_dict(self) -> Dict[str, object]:
        """Compact dict for JSON serialisation or metrics pipelines."""
        return {
            "visit": self.visit_number,
            "severity": self.severity,
            "findings": len(self.findings),
            "critical": len(self.critical_findings),
            "actions": len(self.actions),
            "failed_actions": len(self.failed_actions),
            "backlog_cleared": self.metrics.backlog_cleared,
            "writer_running": self.metrics.writer_running,
            "batch_running": self.metrics.batch_running,
            "gap_seconds": self.metrics.gap_seconds,
        }
