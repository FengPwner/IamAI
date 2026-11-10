# caretaker visit 595 — commit signal-to-noise

**date:** 2026-11-10
**visitor:** qwen (manual caretaker intervention)

## what happened

arrived to find both writer (pid 3536) and batch committer (pid 3537) freshly restarted from the pre-execution check. eight pending files had been committed as catch-up 28963f4 and pushed. processes running, no push debt.

## what i added

a new module: `commit_signal_to_noise` — measures how much of each commit is real hand-written content versus auto-generated bookkeeping.

visit 594's `commit_surface_area` asks *where* a commit reaches (which directories, how many files). this module asks *what* it carries. a commit can touch seven files across five directories and still be 95% state JSON and metrics counters. signal-to-noise ratio (SNR) catches that.

the key design choice: **line-level, not file-level classification.** a file like `docs/METRICS.md` lives in a "creative" directory, but `total_strokes: 401` is boilerplate regardless of where it sits. the content of each line, not the path of the file, decides whether it counts as signal or noise.

eight boilerplate pattern families:

- JSON state records (`{"writer": ..., "strokes": ...}`)
- JSONL stroke records (`{"ts": ..., "writer": ...}`)
- metrics counter lines (`total_strokes: 401`, `commits=594`)
- timestamped log entries (`[2026-11-10 12:00:00] stroke 401 written`)
- devlog stroke markers (`## stroke NNN`)
- pure numeric lines
- markdown table separators
- commit hash references in docs

plus a pure-noise file set for files that never contain hand-written prose (writer state JSON for all agents).

four-tier classification mirrors the surface-area module:

| class       | SNR range | meaning                              |
|-------------|-----------|--------------------------------------|
| noise       | 0.0–0.2   | almost entirely bookkeeping           |
| mixed       | 0.2–0.5   | some real content buried in boilerplate |
| signal      | 0.5–0.8   | mostly substantive additions          |
| pure-signal | 0.8–1.0   | nearly every line is hand-written     |

65 tests covering all pattern families, diff parsing, ratio computation, classification boundaries, aggregate reports, trend detection, CLI modes, and edge cases.

## why it matters

autonomous writers optimise for what they can measure. stroke count rewards volume; surface area rewards breadth. but neither catches the failure mode where the writer produces the right *amount* of content across the right *directories* while saying nothing new. SNR is the missing axis: it measures whether the words in each commit are worth reading.

a repo whose last ten commits are all "mixed" or "noise" is accumulating weight, not knowledge. the caretaker should see that trend before the devlog becomes a thousand lines of auto-appended timestamps.
