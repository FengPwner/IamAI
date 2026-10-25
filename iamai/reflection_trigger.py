"""reflection_trigger — periodic self-reflection prompts for the writer.

The writer produces strokes every 15 seconds.  Left unchecked, it
generates thousands of short observations without ever pausing to
evaluate whether those observations are coherent, improving, or just
noise.  ``cadence_adherence`` checks tempo; ``stroke_quality_gate``
checks individual output; ``stroke_echo_detector`` checks repetition.
But none of them ask the writer to *stop and think*.

This module is the structured pause.

Every N strokes (default 100), the trigger fires: the writer receives
a prompt asking it to summarise its last N strokes, identify the
strongest and weakest, and articulate one thing to do differently in
the next N.  The reflection is stored alongside the strokes and can
be queried later by caretakers reviewing session quality.

Data model
----------

==================  ====================================================
field               meaning
==================  ====================================================
triggered_at        ISO-8601 timestamp of when the trigger fired
stroke_from         first stroke number in the reflection window
stroke_to           last stroke number in the reflection window
prompt              the reflection question posed to the writer
response            the writer's answer (filled in when completed)
completed_at        ISO-8601 timestamp of the writer's response
==================  ====================================================

Public API
----------

``ReflectionTrigger`` class with:

- ``check(stroke_count)`` — returns True when a new reflection is due.
- ``trigger(stroke_count)`` — fires the reflection, returns a prompt dict.
- ``complete(reflection_id, response)`` — records the writer's answer.
- ``pending()`` — list of unanswered reflections.
- ``history()`` — all reflections, answered or not.
- ``overdue(stroke_count, grace=50)`` — True if any reflection is more
  than *grace* strokes past due without a response.
- ``report()`` — one-line human-readable summary.
- ``stats()`` — dict with completion rate, average response length, etc.

Design notes
------------

The trigger is intentionally stateless across restarts: it reads the
current stroke count and the last triggered_at value, then decides
whether enough strokes have elapsed.  No daemon, no timer, no thread.
The commit_batch loop or writer_loop calls ``check()`` on each cycle.

Reflection prompts rotate through a pool of templates to avoid the
writer learning to produce a canned answer.  The pool is small (8)
and can be extended via ``add_prompt_template(text)``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_INTERVAL = 100  # trigger every N strokes
GRACE_STROKES = 50  # overdue threshold beyond the trigger point
STATE_FILE = "data/reflection_state.json"

PROMPT_TEMPLATES: list[str] = [
    "Summarise your last {n} strokes in two sentences. "
    "Which one was the strongest, and why?",
    "Of your last {n} strokes, which felt most like filler? "
    "What would you write instead?",
    "Name one idea from your last {n} strokes that surprised you. "
    "If none surprised you, say why.",
    "Look at your last {n} strokes. Are you repeating yourself? "
    "If so, what's the loop? If not, what's the thread?",
    "If you could delete one of your last {n} strokes, which "
    "would it be and what would you replace it with?",
    "Rate the diversity of your last {n} strokes from 1-10. "
    "What would push it one point higher?",
    "Your last {n} strokes: what's the one question you kept "
    "avoiding? Write it down now.",
    "Imagine a new caretaker reads only your last {n} strokes. "
    "What impression would they form? Is it accurate?",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_id(stroke_from: int, stroke_to: int) -> str:
    """Deterministic ID from stroke range."""
    raw = f"refl-{stroke_from}-{stroke_to}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load_state(path: str | Path) -> dict[str, Any]:
    """Load persisted state; return empty dict if missing."""
    p = Path(path)
    if not p.exists():
        return {"reflections": [], "prompt_index": 0}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("reflections", [])
        data.setdefault("prompt_index", 0)
        return data
    except (json.JSONDecodeError, OSError):
        return {"reflections": [], "prompt_index": 0}


def _save_state(path: str | Path, state: dict[str, Any]) -> None:
    """Persist state atomically."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# ReflectionTrigger
# ---------------------------------------------------------------------------


class ReflectionTrigger:
    """Periodic self-reflection trigger for the writer.

    Parameters
    ----------
    interval : int
        Number of strokes between reflections (default 100).
    state_path : str | Path
        Path to the JSON state file.
    now_fn : callable, optional
        Injectable clock for testing.
    """

    def __init__(
        self,
        interval: int = DEFAULT_INTERVAL,
        state_path: str | Path = STATE_FILE,
        now_fn=None,
    ):
        if interval < 1:
            raise ValueError(f"interval must be >= 1, got {interval}")
        self.interval = interval
        self.state_path = Path(state_path)
        self._now = now_fn or _now
        self._state = _load_state(self.state_path)
        self._custom_templates: list[str] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def reflections(self) -> list[dict[str, Any]]:
        """All reflections (completed and pending)."""
        return list(self._state["reflections"])

    @property
    def last_triggered_stroke(self) -> int:
        """Stroke number of the most recent trigger, or 0."""
        if not self._state["reflections"]:
            return 0
        return self._state["reflections"][-1]["stroke_to"]

    @property
    def all_templates(self) -> list[str]:
        """Combined pool of built-in and custom prompt templates."""
        return PROMPT_TEMPLATES + self._custom_templates

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def check(self, stroke_count: int) -> bool:
        """Return True if a new reflection is due at *stroke_count*."""
        if stroke_count < self.interval:
            return False
        last = self.last_triggered_stroke
        return (stroke_count - last) >= self.interval

    def trigger(self, stroke_count: int) -> dict[str, Any]:
        """Fire a reflection trigger at *stroke_count*.

        Returns the new reflection record (prompt included).

        Raises
        ------
        ValueError
            If a reflection is not yet due at this stroke count.
        """
        if not self.check(stroke_count):
            raise ValueError(
                f"reflection not due at stroke {stroke_count} "
                f"(last triggered at {self.last_triggered_stroke}, "
                f"interval={self.interval})"
            )

        stroke_from = self.last_triggered_stroke + 1
        stroke_to = stroke_count
        prompt_idx = self._state["prompt_index"] % len(self.all_templates)
        prompt_text = self.all_templates[prompt_idx].format(
            n=stroke_to - stroke_from + 1
        )

        reflection = {
            "id": _make_id(stroke_from, stroke_to),
            "triggered_at": self._now().isoformat(),
            "stroke_from": stroke_from,
            "stroke_to": stroke_to,
            "prompt": prompt_text,
            "response": None,
            "completed_at": None,
        }

        self._state["reflections"].append(reflection)
        self._state["prompt_index"] = prompt_idx + 1
        self._save()
        return reflection

    def complete(self, reflection_id: str, response: str) -> dict[str, Any]:
        """Record the writer's response to a pending reflection.

        Returns the updated reflection record.

        Raises
        ------
        KeyError
            If no reflection with *reflection_id* exists.
        ValueError
            If the reflection was already completed.
        """
        for ref in self._state["reflections"]:
            if ref["id"] == reflection_id:
                if ref["completed_at"] is not None:
                    raise ValueError(
                        f"reflection {reflection_id} already completed "
                        f"at {ref['completed_at']}"
                    )
                ref["response"] = response
                ref["completed_at"] = self._now().isoformat()
                self._save()
                return ref
        raise KeyError(f"no reflection with id {reflection_id}")

    def pending(self) -> list[dict[str, Any]]:
        """Return all unanswered reflections."""
        return [r for r in self._state["reflections"] if r["completed_at"] is None]

    def history(self) -> list[dict[str, Any]]:
        """Return all reflections (answered and unanswered)."""
        return list(self._state["reflections"])

    def overdue(self, stroke_count: int, grace: int = GRACE_STROKES) -> bool:
        """True if any pending reflection is more than *grace* strokes overdue."""
        for ref in self.pending():
            if (stroke_count - ref["stroke_to"]) > grace:
                return True
        return False

    def overdue_reflections(
        self, stroke_count: int, grace: int = GRACE_STROKES
    ) -> list[dict[str, Any]]:
        """Return pending reflections that are more than *grace* strokes overdue."""
        return [
            r
            for r in self.pending()
            if (stroke_count - r["stroke_to"]) > grace
        ]

    def report(self) -> str:
        """One-line human-readable summary."""
        total = len(self._state["reflections"])
        completed = total - len(self.pending())
        last = self.last_triggered_stroke
        return (
            f"reflection_trigger: {completed}/{total} completed, "
            f"last triggered at stroke {last}, "
            f"interval={self.interval}"
        )

    def stats(self) -> dict[str, Any]:
        """Summary statistics."""
        total = len(self._state["reflections"])
        completed_list = [
            r for r in self._state["reflections"] if r["completed_at"] is not None
        ]
        completed = len(completed_list)
        pending_count = total - completed

        avg_response_len = 0.0
        if completed_list:
            lengths = [
                len(r.get("response", "") or "")
                for r in completed_list
            ]
            avg_response_len = sum(lengths) / len(lengths)

        completion_rate = (completed / total) if total > 0 else 0.0

        return {
            "total_reflections": total,
            "completed": completed,
            "pending": pending_count,
            "completion_rate": round(completion_rate, 3),
            "avg_response_length": round(avg_response_len, 1),
            "last_triggered_stroke": self.last_triggered_stroke,
            "interval": self.interval,
        }

    # ------------------------------------------------------------------
    # Template management
    # ------------------------------------------------------------------

    def add_prompt_template(self, text: str) -> None:
        """Add a custom prompt template to the pool.

        The template must contain ``{n}`` as a placeholder for the
        stroke window size.
        """
        if "{n}" not in text:
            raise ValueError("template must contain {n} placeholder")
        self._custom_templates.append(text)

    @property
    def custom_templates(self) -> list[str]:
        return list(self._custom_templates)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        _save_state(self.state_path, self._state)

    def reload(self) -> None:
        """Reload state from disk (e.g. after external modification)."""
        self._state = _load_state(self.state_path)
