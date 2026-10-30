"""stroke_half_life — measure topic recurrence intervals.

``content_diversity`` tells you if the kind distribution is balanced.
``topic_drift`` tells you if the subject matter is shifting over time.
But neither answers a question every long-running writer eventually
asks: **how often does the writer circle back to a given topic?**

This module fills that gap.  Given a sequence of (topic, timestamp)
pairs, it computes the *recurrence gap* for each topic — the average
time between consecutive appearances — and classifies each topic as
**hot** (frequently revisited), **warm** (regular cadence), or **cold**
(rarely revisited or abandoned).

The half-life metaphor is deliberate: a topic with a short half-life
decays quickly (the writer moves on); a topic with a long half-life
persists (the writer keeps returning).  Unlike radioactive decay,
topics can speed up or slow down, so we also report a *trend*:
is the gap shrinking (topic heating up) or growing (cooling down)?

Design choices
--------------

- **No external dependencies** — pure Python, works on any topic
  labelling scheme (tags, kinds, filenames, or free-text labels).
- **Streaming-friendly** — accepts a list but also exposes an
  ``observe(topic, ts)`` method for incremental use.
- **Actionable** — classifies topics so caretakers can spot anomalies
  at a glance: "why is *metrics* cold?" / "why is *thought* hot?"

Verdicts
--------

- **hot**  — recurrence gap < ``hot_threshold``  (topic revisited often)
- **warm** — recurrence gap between ``hot_threshold`` and ``cold_threshold``
- **cold** — recurrence gap > ``cold_threshold`` (topic rarely revisited)
- **dormant** — seen only once, or no occurrence in the window

Trend:

- **heating** — recent gap < 0.7 × average gap
- **steady**  — recent gap within ±30 % of average gap
- **cooling** — recent gap > 1.3 × average gap

Usage::

    from iamai.stroke_half_life import TopicHalfLife

    thl = TopicHalfLife()
    thl.observe("thought", 1000)
    thl.observe("devlog",  1030)
    thl.observe("thought", 1060)
    thl.observe("garden",  1090)
    thl.observe("thought", 1120)

    thl.gap("thought")        # 60.0  (avg of 60, 60)
    thl.classify("thought")   # depends on thresholds
    thl.trend("thought")      # "steady"
    thl.summary()             # {"thought": {...}, "devlog": {...}, ...}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_HOT_S = 120.0       # < 2 min → hot
_DEFAULT_COLD_S = 1800.0     # > 30 min → cold
_DEFAULT_WINDOW_S = 3600.0   # 1 hour rolling window


# ---------------------------------------------------------------------------
# Per-topic record
# ---------------------------------------------------------------------------

@dataclass
class _TopicRecord:
    """Internal: timestamps of observed occurrences for one topic."""

    timestamps: List[float] = field(default_factory=list)

    def add(self, ts: float) -> None:
        self.timestamps.append(ts)

    @property
    def count(self) -> int:
        return len(self.timestamps)

    def gaps(self) -> List[float]:
        """Return sorted list of consecutive gaps."""
        ts = sorted(self.timestamps)
        return [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]

    def avg_gap(self) -> Optional[float]:
        g = self.gaps()
        if not g:
            return None
        return sum(g) / len(g)

    def last_gap(self) -> Optional[float]:
        g = self.gaps()
        if not g:
            return None
        return g[-1]

    def last_seen(self) -> Optional[float]:
        if not self.timestamps:
            return None
        return max(self.timestamps)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class TopicHalfLife:
    """Track topic recurrence intervals and classify their cadence."""

    def __init__(
        self,
        hot_threshold: float = _DEFAULT_HOT_S,
        cold_threshold: float = _DEFAULT_COLD_S,
        window_s: float = _DEFAULT_WINDOW_S,
    ) -> None:
        self.hot_threshold = hot_threshold
        self.cold_threshold = cold_threshold
        self.window_s = window_s
        self._records: Dict[str, _TopicRecord] = {}

    # ------------------------------------------------------------------
    # Observe
    # ------------------------------------------------------------------

    def observe(self, topic: str, ts: float) -> None:
        """Record an occurrence of *topic* at time *ts*."""
        if topic not in self._records:
            self._records[topic] = _TopicRecord()
        self._records[topic].add(ts)

    def observe_many(
        self, events: Sequence[Tuple[str, float]]
    ) -> None:
        """Bulk-load a sequence of (topic, timestamp) pairs."""
        for topic, ts in events:
            self.observe(topic, ts)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def topics(self) -> List[str]:
        """All observed topics, sorted by last-seen descending."""
        return sorted(
            self._records.keys(),
            key=lambda t: self._records[t].last_seen() or 0,
            reverse=True,
        )

    def count(self, topic: str) -> int:
        r = self._records.get(topic)
        return r.count if r else 0

    def gap(self, topic: str) -> Optional[float]:
        """Average recurrence gap in seconds, or None if < 2 occurrences."""
        r = self._records.get(topic)
        if r is None:
            return None
        return r.avg_gap()

    def classify(self, topic: str) -> str:
        """Return 'hot', 'warm', 'cold', or 'dormant'."""
        r = self._records.get(topic)
        if r is None or r.count < 2:
            return "dormant"
        avg = r.avg_gap()
        if avg is None:
            return "dormant"
        if avg < self.hot_threshold:
            return "hot"
        if avg <= self.cold_threshold:
            return "warm"
        return "cold"

    def trend(self, topic: str) -> str:
        """Return 'heating', 'steady', or 'cooling'.

        Compares the most recent gap against the historical average.
        """
        r = self._records.get(topic)
        if r is None or r.count < 3:
            return "steady"
        avg = r.avg_gap()
        last = r.last_gap()
        if avg is None or last is None or avg == 0:
            return "steady"
        ratio = last / avg
        if ratio < 0.7:
            return "heating"
        if ratio > 1.3:
            return "cooling"
        return "steady"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, dict]:
        """Return a dict keyed by topic with gap, classify, trend."""
        out: Dict[str, dict] = {}
        for topic in self.topics:
            r = self._records[topic]
            out[topic] = {
                "count": r.count,
                "avg_gap_s": round(r.avg_gap(), 2) if r.avg_gap() is not None else None,
                "last_seen": r.last_seen(),
                "classify": self.classify(topic),
                "trend": self.trend(topic),
            }
        return out

    def report(self) -> str:
        """Human-readable one-liner per topic."""
        lines = []
        for topic in self.topics:
            s = self.summary()[topic]
            gap_str = f"{s['avg_gap_s']:.0f}s" if s["avg_gap_s"] is not None else "—"
            lines.append(
                f"  {topic:20s}  ×{s['count']:4d}  gap {gap_str:>8s}  "
                f"{s['classify']:8s}  {s['trend']}"
            )
        header = f"Topic half-life report ({len(self.topics)} topics)\n"
        return header + "\n".join(lines)

    # ------------------------------------------------------------------
    # Convenience: load from strokes.jsonl-style dicts
    # ------------------------------------------------------------------

    @classmethod
    def from_strokes(
        cls,
        strokes: Sequence[dict],
        topic_key: str = "kind",
        ts_key: str = "at",
        **kwargs,
    ) -> "TopicHalfLife":
        """Build a TopicHalfLife from a list of stroke dicts.

        Each dict must have *topic_key* (default "kind") and *ts_key*
        (default "at").  Timestamps are parsed with
        ``datetime.fromisoformat``; non-ISO strings are skipped.
        """
        import datetime as _dt

        thl = cls(**kwargs)
        for s in strokes:
            topic = s.get(topic_key)
            raw_ts = s.get(ts_key)
            if topic is None or raw_ts is None:
                continue
            try:
                dt = _dt.datetime.fromisoformat(str(raw_ts))
                ts = dt.timestamp()
            except (ValueError, TypeError):
                continue
            thl.observe(str(topic), ts)
        return thl


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def classify_topic(
    avg_gap_s: Optional[float],
    hot_threshold: float = _DEFAULT_HOT_S,
    cold_threshold: float = _DEFAULT_COLD_S,
) -> str:
    """Standalone classify without a TopicHalfLife instance."""
    if avg_gap_s is None:
        return "dormant"
    if avg_gap_s < hot_threshold:
        return "hot"
    if avg_gap_s <= cold_threshold:
        return "warm"
    return "cold"


def trend_from_gaps(gaps: Sequence[float]) -> str:
    """Standalone trend from a list of gaps (no TopicHalfLife needed)."""
    if len(gaps) < 2:
        return "steady"
    avg = sum(gaps) / len(gaps)
    if avg == 0:
        return "steady"
    ratio = gaps[-1] / avg
    if ratio < 0.7:
        return "heating"
    if ratio > 1.3:
        return "cooling"
    return "steady"
