"""commit_temperature — track which files change most often.

Every commit touches files.  Some files are touched constantly
(data/strokes.jsonl, writer_state); others haven't changed in months.
The temperature of a file is a simple metric: how many commits
touched it in the last N commits, normalised to [0, 1].

Use cases
---------
- **Hot files:** high temperature means the file is actively evolving.
  For a self-writing repo, ``data/strokes.jsonl`` will always be hot —
  that's expected.  If ``notes/conventions.md`` suddenly heats up,
  something unusual is happening.
- **Cold files:** zero temperature means a file hasn't been touched
  recently.  Useful for identifying dead weight or stable foundations.
- **Temperature shift:** comparing two windows reveals which files
  are heating up or cooling down — a proxy for where the repo's
  attention is moving.

Usage::

    from iamai.commit_temperature import CommitThermometer

    thermo = CommitThermometer()
    # Option 1: feed commit diffs directly
    thermo.ingest_diffs([
        {"files": ["a.py", "b.py"]},
        {"files": ["a.py", "c.md"]},
        {"files": ["a.py"]},
    ])

    # Option 2: feed from git log (caller runs subprocess)
    thermo.ingest_file_lists([
        ["a.py", "b.py"],
        ["a.py", "c.md"],
        ["a.py"],
    ])

    report = thermo.report(window=3)
    print(report.temperatures)     # {'a.py': 1.0, 'b.py': 0.33, 'c.md': 0.33}
    print(report.hot_files)        # ['a.py']
    print(report.cold_files)       # files with 0 temperature (none here)
    print(report.heat_index)       # overall repo heat concentration

Classification::

    hot        temperature >= 0.60   — actively changing
    warm       0.30 <= temperature < 0.60
    cool       0.10 <= temperature < 0.30
    cold       temperature < 0.10    — essentially static

Design:
  - Pure-Python, no subprocess, no git dependency.
  - Caller is responsible for extracting file lists from commits.
  - Supports both incremental feeding and batch mode.
  - Frozen dataclass output; internal state is mutable for streaming.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Classification thresholds
# ---------------------------------------------------------------------------
HOT_THRESHOLD = 0.60
WARM_THRESHOLD = 0.30
COOL_THRESHOLD = 0.10


def classify(temperature: float) -> str:
    """Classify a file's temperature into a human-readable band."""
    if temperature >= HOT_THRESHOLD:
        return "hot"
    if temperature >= WARM_THRESHOLD:
        return "warm"
    if temperature >= COOL_THRESHOLD:
        return "cool"
    return "cold"


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TemperatureReport:
    """Snapshot of file temperatures over a commit window."""

    window: int
    total_files: int
    temperatures: dict[str, float]
    classifications: dict[str, str]
    hot_files: list[str]
    warm_files: list[str]
    cool_files: list[str]
    cold_files: list[str]
    heat_index: float  # Gini-like concentration: 0=uniform, 1=one file

    def to_dict(self) -> dict:
        return {
            "window": self.window,
            "total_files": self.total_files,
            "temperatures": self.temperatures,
            "classifications": self.classifications,
            "hot_files": self.hot_files,
            "warm_files": self.warm_files,
            "cool_files": self.cool_files,
            "cold_files": self.cold_files,
            "heat_index": round(self.heat_index, 4),
        }


# ---------------------------------------------------------------------------
# Thermometer
# ---------------------------------------------------------------------------
class CommitThermometer:
    """Accumulates per-commit file lists and computes temperatures."""

    def __init__(self) -> None:
        self._commits: list[list[str]] = []

    # -- ingestion ----------------------------------------------------------

    def ingest_file_lists(self, commits: Sequence[Sequence[str]]) -> None:
        """Add a batch of commits, each a list of changed file paths."""
        for c in commits:
            self._commits.append(list(c))

    def ingest_diffs(self, diffs: Sequence[dict]) -> None:
        """Convenience: extract ``files`` key from a list of diff dicts."""
        for d in diffs:
            files = d.get("files", [])
            if files:
                self._commits.append(list(files))

    # -- queries ------------------------------------------------------------

    @property
    def commit_count(self) -> int:
        return len(self._commits)

    def report(self, window: int | None = None) -> TemperatureReport:
        """Compute temperatures over the last *window* commits.

        Parameters
        ----------
        window : int or None
            Number of recent commits to analyse.  ``None`` means all.

        Returns
        -------
        TemperatureReport
        """
        if not self._commits:
            return TemperatureReport(
                window=0,
                total_files=0,
                temperatures={},
                classifications={},
                hot_files=[],
                warm_files=[],
                cool_files=[],
                cold_files=[],
                heat_index=0.0,
            )

        commits = self._commits[-window:] if window else self._commits
        actual_window = len(commits)

        # Count how many commits touch each file (deduplicate within a commit)
        counter: Counter[str] = Counter()
        for c in commits:
            for f in set(c):
                counter[f] += 1

        # Temperature = fraction of commits that touched the file
        temperatures: dict[str, float] = {}
        for fname, count in counter.items():
            temperatures[fname] = count / actual_window

        # Sort by temperature descending
        temperatures = dict(
            sorted(temperatures.items(), key=lambda kv: (-kv[1], kv[0]))
        )

        # Classify
        classifications = {f: classify(t) for f, t in temperatures.items()}

        hot = [f for f, c in classifications.items() if c == "hot"]
        warm = [f for f, c in classifications.items() if c == "warm"]
        cool = [f for f, c in classifications.items() if c == "cool"]
        cold = [f for f, c in classifications.items() if c == "cold"]

        # Heat index: how concentrated are the changes?
        # Normalised entropy: 0 = uniform, 1 = all changes in one file
        heat_index = _compute_heat_index(temperatures)

        return TemperatureReport(
            window=actual_window,
            total_files=len(temperatures),
            temperatures=temperatures,
            classifications=classifications,
            hot_files=hot,
            warm_files=warm,
            cool_files=cool,
            cold_files=cold,
            heat_index=heat_index,
        )

    def shift(self, old_window: int, new_window: int) -> dict[str, float]:
        """Compare temperatures between two windows.

        Returns a dict of ``{file: delta}`` where positive means heating
        and negative means cooling.  Only includes files present in
        either window.
        """
        old_report = self.report(window=old_window)
        # For the "new" window we use the most recent commits
        new_commits = self._commits[-new_window:] if self._commits else []
        temp_thermo = CommitThermometer()
        temp_thermo.ingest_file_lists(new_commits)
        new_report = temp_thermo.report()

        all_files = set(old_report.temperatures) | set(new_report.temperatures)
        shifts: dict[str, float] = {}
        for f in sorted(all_files):
            old_t = old_report.temperatures.get(f, 0.0)
            new_t = new_report.temperatures.get(f, 0.0)
            delta = new_t - old_t
            if abs(delta) > 0.001:
                shifts[f] = round(delta, 4)
        return shifts

    def reset(self) -> None:
        """Clear all accumulated data."""
        self._commits.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_heat_index(temperatures: dict[str, float]) -> float:
    """Normalised concentration index (0 = uniform, 1 = single file).

    Uses a simplified Gini approach: sum of squared shares, normalised
    against the theoretical maximum (all heat in one file).
    """
    if not temperatures:
        return 0.0

    n = len(temperatures)
    if n <= 1:
        return 1.0

    total = sum(temperatures.values())
    if total == 0:
        return 0.0

    shares = [t / total for t in temperatures.values()]
    hhi = sum(s * s for s in shares)  # Herfindahl–Hirschman Index

    # Normalise: minimum HHI is 1/n (uniform), maximum is 1.0 (one file)
    min_hhi = 1.0 / n
    max_hhi = 1.0
    if max_hhi == min_hhi:
        return 0.0

    return (hhi - min_hhi) / (max_hhi - min_hhi)
