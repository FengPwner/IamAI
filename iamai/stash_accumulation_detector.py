"""stash_accumulation_detector — measure git stash pile-up and classify risk.

A growing stash list is a leading indicator of process debt.  Stashes
are meant to be transient — pop, apply, drop.  When they accumulate it
means one of:

1. **Orphaned stashes** — a process stashed before a pull but crashed
   before popping, leaving WIP entries that will never be reclaimed.
2. **Conflict avoidance** — a script stashes around every pull because
   it cannot guarantee a clean tree, even when the stash contents are
   already committed elsewhere.
3. **Merge-back fear** — the stash is old enough that popping it would
   produce conflicts the automation is not equipped to resolve, so it
   is left as a frozen snapshot that grows the index forever.

Each category has a different fix.  This module classifies the stash
list so the caretaker can pick the right one instead of blindly
running ``git stash clear``.

Public API::

    from iamai.stash_accumulation_detector import (
        StashEntry, StashHealth,
        parse_stash_list, assess_stash_health, recommend_cleanup,
    )

    entries = parse_stash_list(stash_list_output)
    health  = assess_stash_health(entries)
    # StashHealth(count=36, orphaned=28, aged_days_max=42, risk='high')

    plan = recommend_cleanup(health)
    # {"action": "selective_drop", "drop_indices": [4..36],
    #    "keep_indices": [0, 1], "reason": "orphaned wip older than 7d"}

Health tiers
------------

========  ============================================================
tier      meaning
========  ============================================================
clean     0–2 stashes, all recent (<3 days)
nominal   3–5 stashes, none older than 7 days
elevated  6–15 stashes, or at least one older than 7 days
high      16–30 stashes, or at least one older than 14 days
critical  31+ stashes, or at least one older than 30 days
========  ============================================================

Cleanup strategies
------------------

- **selective_drop** — drop entries older than a threshold while
  keeping recent ones.  Safest; preserves in-flight work.
- **drop_all** — ``git stash clear``.  Use only when every entry is
  orphaned and the working tree is already clean.
- **pop_and_commit** — pop the top N entries, commit their contents,
  then drop.  Appropriate when stashes contain uncommitted work that
  should be preserved.
- **investigate** — too many named/labeled stashes; a human should
  decide which are intentional saves vs. accidental WIP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StashEntry:
    """One line from ``git stash list``."""

    index: int
    ref: str  # e.g. "stash@{0}"
    branch: str  # branch the stash was created on
    message: str  # user-supplied or auto-generated message
    timestamp: Optional[datetime] = None  # parsed from message when possible
    is_wip: bool = True  # True for auto-generated WIP stashes
    age_days: float = 0.0  # days since stash creation

    @property
    def is_named(self) -> bool:
        """True when the stash has a user-supplied label (not WIP)."""
        return not self.is_wip


@dataclass
class StashHealth:
    """Aggregate assessment of stash accumulation."""

    count: int = 0
    orphaned: int = 0  # WIP entries older than 3 days
    named: int = 0  # user-labeled stashes
    wip: int = 0  # auto-generated WIP stashes
    aged_days_max: float = 0.0  # oldest entry age in days
    aged_days_median: float = 0.0
    risk: str = "clean"  # clean | nominal | elevated | high | critical
    orphan_ratio: float = 0.0  # orphaned / count


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# git stash list output format:
#   stash@{0}: WIP on main: abc1234 commit message
#   stash@{1}: On main: pre-pull-stash
#   stash@{2}: WIP on main: 8037f85 caretaker visit 747: ...

_STASH_LINE_RE = re.compile(
    r"^stash@\{(\d+)\}:\s+"
    r"(WIP\s+on|On)\s+"
    r"(\S+):\s+"
    r"(.+)$"
)

_DATE_HINT_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
)


def parse_stash_list(raw: str, now: Optional[datetime] = None) -> List[StashEntry]:
    """Parse ``git stash list`` output into structured entries.

    Parameters
    ----------
    raw : str
        Raw output of ``git stash list``.
    now : datetime, optional
        Reference time for age calculation.  Defaults to UTC now.

    Returns
    -------
    list[StashEntry]
    """
    if now is None:
        now = datetime.now(timezone.utc)

    entries: List[StashEntry] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = _STASH_LINE_RE.match(line)
        if not m:
            continue

        index = int(m.group(1))
        prefix = m.group(2)  # "WIP on" or "On"
        branch = m.group(3)
        message = m.group(4).strip()
        is_wip = prefix.startswith("WIP")

        # Try to extract a date from the message
        ts = None
        dm = _DATE_HINT_RE.search(message)
        if dm:
            try:
                ts = datetime(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)),
                              tzinfo=timezone.utc)
            except ValueError:
                pass

        age_days = 0.0
        if ts is not None:
            age_days = max(0.0, (now - ts).total_seconds() / 86400)

        entries.append(StashEntry(
            index=index,
            ref=f"stash@{{{index}}}",
            branch=branch,
            message=message,
            timestamp=ts,
            is_wip=is_wip,
            age_days=age_days,
        ))

    return entries


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

_ORPHAN_THRESHOLD_DAYS = 3.0


def assess_stash_health(
    entries: List[StashEntry],
    now: Optional[datetime] = None,
) -> StashHealth:
    """Classify the overall health of the stash list.

    Parameters
    ----------
    entries : list[StashEntry]
        Parsed stash entries.
    now : datetime, optional
        Reference time (unused if entries already have age_days).

    Returns
    -------
    StashHealth
    """
    count = len(entries)
    if count == 0:
        return StashHealth(risk="clean")

    wip_entries = [e for e in entries if e.is_wip]
    named_entries = [e for e in entries if e.is_named]
    orphaned = [e for e in wip_entries if e.age_days > _ORPHAN_THRESHOLD_DAYS]

    ages = sorted(e.age_days for e in entries if e.age_days > 0)
    max_age = max(ages) if ages else 0.0
    median_age = ages[len(ages) // 2] if ages else 0.0

    risk = _classify_risk(count, max_age)

    return StashHealth(
        count=count,
        orphaned=len(orphaned),
        named=len(named_entries),
        wip=len(wip_entries),
        aged_days_max=max_age,
        aged_days_median=median_age,
        risk=risk,
        orphan_ratio=len(orphaned) / count if count > 0 else 0.0,
    )


def _classify_risk(count: int, max_age_days: float) -> str:
    """Map count + max age to a risk tier."""
    if count >= 31 or max_age_days > 30:
        return "critical"
    if count >= 16 or max_age_days > 14:
        return "high"
    if count >= 6 or max_age_days > 7:
        return "elevated"
    if count >= 3:
        return "nominal"
    return "clean"


# ---------------------------------------------------------------------------
# Cleanup recommendations
# ---------------------------------------------------------------------------

def recommend_cleanup(health: StashHealth, entries: Optional[List[StashEntry]] = None) -> Dict:
    """Produce a cleanup plan based on health assessment.

    Parameters
    ----------
    health : StashHealth
        Result of :func:`assess_stash_health`.
    entries : list[StashEntry], optional
        Original entries for index-level recommendations.

    Returns
    -------
    dict
        Cleanup plan with action, indices, and reasoning.
    """
    if health.risk == "clean":
        return {"action": "none", "reason": "stash list is healthy"}

    if health.risk == "nominal" and health.orphaned == 0:
        return {"action": "none", "reason": "all stashes are recent and active"}

    # Determine which entries to drop vs keep
    drop_indices: List[int] = []
    keep_indices: List[int] = []

    if entries:
        for e in entries:
            if e.is_wip and e.age_days > _ORPHAN_THRESHOLD_DAYS:
                drop_indices.append(e.index)
            else:
                keep_indices.append(e.index)
    else:
        # Without entries, give count-based guidance
        drop_indices = list(range(health.wip, health.count))
        keep_indices = list(range(min(health.wip, 3)))

    if not drop_indices and health.risk in ("high", "critical"):
        return {
            "action": "investigate",
            "reason": f"{health.count} stashes but none clearly orphaned; "
                      "human review recommended",
            "count": health.count,
        }

    if health.orphan_ratio > 0.8 and health.risk in ("high", "critical"):
        return {
            "action": "drop_all",
            "reason": f"{health.orphaned}/{health.count} entries are orphaned WIP "
                      f"older than {_ORPHAN_THRESHOLD_DAYS:.0f} days",
            "drop_indices": drop_indices,
            "keep_indices": keep_indices,
        }

    return {
        "action": "selective_drop",
        "reason": f"drop {len(drop_indices)} orphaned WIP entries, "
                  f"keep {len(keep_indices)} recent/labeled entries",
        "drop_indices": drop_indices,
        "keep_indices": keep_indices,
    }
