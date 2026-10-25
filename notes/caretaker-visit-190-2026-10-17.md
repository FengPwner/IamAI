# caretaker visit 190

**when:** 2026-10-17 ~22:00 CST (14:00 UTC)
**what happened:** writer (pid 25182) and batch committer (pid 25183) both running after pre-exec restarted them earlier. No backlog — batch committer current. This visit adds a new echo detection module.

## new content: `stroke_echo_detector`

`iamai/stroke_echo_detector.py` fills a gap between the existing `stroke_novelty` (exact duplicate detection) and `template_loop_detector` (structural template matching). It detects **near-duplicate** strokes — texts that are *almost* the same, like the recurring pattern:

```
tree is 839 files; 174049 lines is a lot for a toy
tree is 839 files; 174084 lines is a lot for a toy
```

Only a few digits change, but `stroke_novelty` wouldn't catch it (the strings aren't identical) and `template_loop_detector` requires a structural template match. The echo detector uses `difflib.SequenceMatcher` character-level similarity to catch this middle ground.

**Core API:**
- `text_similarity(a, b)` — character-level ratio (0.0–1.0)
- `detect_echoes(texts, threshold, window)` — sliding window scan, returns `EchoEvent` list
- `echo_report(texts)` — full report with density, worst ratio, verdict (`clean`/`mild`/`echoing`)

**Thresholds:**
- `ECHO_THRESHOLD` = 0.85 (minimum ratio to flag)
- `WINDOW_SIZE` = 20 (comparison window)

**35 tests cover:** text similarity (identical, different, one-char diff, empty, number substitution, reordered words), preview truncation (short, long, whitespace, boundary), echo detection (no echoes, exact/near duplicates, empty/single input, threshold sensitivity, window boundaries, multiple echoes, sort order), data class properties (severity tiers, frozen dataclass), report statistics (clean/mild/echoing verdicts, density, summary formatting, singular/plural), and full integration pipeline.

## process status

| item | value |
|------|-------|
| writer pid | 25182 |
| batch pid | 25183 |
| pending | 0 |
| strokes | 400+ (writer actively producing) |
| gap | healthy (writer cadence nominal) |

## observation

The system recovered cleanly from the process recycle earlier today. The longest gap field still shows the pre-restart stall (~1692s) but it's a decaying maximum — new strokes will push it out of the rolling window. No intervention needed. The new echo detector will help future caretakers spot the subtle repetition patterns that fall between exact duplicates and template loops.
