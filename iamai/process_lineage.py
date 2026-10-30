"""process_lineage — track restart chains as a family tree.

Each restart creates a new process generation.  This module records
the succession of PIDs as a lineage, answering: "how many ancestors
does the current writer have?" and "when did each generation die?"

A lineage is stored as a list of ``Generation`` records, each with:

=================  ================================================
field              meaning
=================  ================================================
``pid``            process ID of this generation
``born``           timestamp when process started
``died``           timestamp when process ended (None if alive)
``parent_pid``     PID of the previous generation (None for first)
``cause``          reason for death: "container", "oom", "manual", "unknown"
``strokes``        stroke count at time of death
=================  ================================================

Usage:

>>> from datetime import datetime, timezone
>>> tree = ProcessLineage()
>>> g1 = Generation(pid=100, born=datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc),
...                 died=datetime(2026, 10, 30, 1, 0, 0, tzinfo=timezone.utc),
...                 parent_pid=None, cause="container", strokes=150)
>>> g2 = Generation(pid=200, born=datetime(2026, 10, 30, 1, 5, 0, tzinfo=timezone.utc),
...                 died=None, parent_pid=100, cause=None, strokes=None)
>>> tree.add(g1)
>>> tree.add(g2)
>>> tree.current_generation()
2
>>> tree.depth()
2
>>> tree.is_orphaned()  # g2 has no parent? No, parent_pid=100
False

Zero dependencies.  stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Generation:
    """A single process generation in the lineage."""
    pid: int
    born: datetime
    died: Optional[datetime] = None
    parent_pid: Optional[int] = None
    cause: Optional[str] = None
    strokes: Optional[int] = None

    def lifespan_s(self) -> Optional[float]:
        """Seconds this generation lived.  None if still alive."""
        if self.died is None:
            return None
        return (self.died - self.born).total_seconds()

    def is_alive(self) -> bool:
        """True if this generation has no death timestamp."""
        return self.died is None

    def to_dict(self) -> dict:
        """Serialize to plain dict."""
        return {
            "pid": self.pid,
            "born": self.born.isoformat() if self.born else None,
            "died": self.died.isoformat() if self.died else None,
            "parent_pid": self.parent_pid,
            "cause": self.cause,
            "strokes": self.strokes,
        }


class ProcessLineage:
    """Track a sequence of process restarts as a family tree."""

    def __init__(self) -> None:
        self._generations: List[Generation] = []

    def add(self, gen: Generation) -> None:
        """Add a generation to the lineage."""
        self._generations.append(gen)

    def depth(self) -> int:
        """Number of generations recorded."""
        return len(self._generations)

    def current_generation(self) -> int:
        """1-based index of the most recent generation."""
        return len(self._generations)

    def current_pid(self) -> Optional[int]:
        """PID of the most recent generation."""
        if not self._generations:
            return None
        return self._generations[-1].pid

    def is_orphaned(self) -> bool:
        """True if the latest generation has no recorded parent (and depth > 1)."""
        if len(self._generations) <= 1:
            return False
        return self._generations[-1].parent_pid is None

    def ancestors(self, pid: int) -> List[int]:
        """Return the chain of ancestor PIDs for a given PID."""
        chain = []
        current = pid
        gen_by_pid = {g.pid: g for g in self._generations}
        while current in gen_by_pid and gen_by_pid[current].parent_pid is not None:
            parent = gen_by_pid[current].parent_pid
            chain.append(parent)
            current = parent
        return chain

    def total_lifespan_s(self) -> float:
        """Sum of all recorded lifespans (excluding still-alive generations)."""
        total = 0.0
        for g in self._generations:
            ls = g.lifespan_s()
            if ls is not None:
                total += ls
        return total

    def average_lifespan_s(self) -> Optional[float]:
        """Mean lifespan of dead generations.  None if all alive."""
        dead = [g for g in self._generations if g.died is not None]
        if not dead:
            return None
        return self.total_lifespan_s() / len(dead)

    def restart_causes(self) -> dict:
        """Count restarts by cause."""
        counts: dict = {}
        for g in self._generations:
            if g.cause:
                counts[g.cause] = counts.get(g.cause, 0) + 1
        return counts

    def to_list(self) -> list:
        """Serialize all generations to a list of dicts."""
        return [g.to_dict() for g in self._generations]

    def __repr__(self) -> str:
        return f"ProcessLineage(depth={self.depth()}, current_pid={self.current_pid()})"
