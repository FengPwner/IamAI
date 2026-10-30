# caretaker visit 248 — 2026-10-20 19:00 GMT+8

## arrival state

- writer: running (pid 15621, restarted by pre-exec harness at 19:00)
- batch: running (pid 15622, same)
- git lock: clean (lock cleared before arrival)
- pending files: 9 (accumulated during the dead period between visits
  247 and 248 — writer produced output but no commit ran)
- unpushed commits: 0
- stall flag: STALL — writer silent past 2× its cadence (gap 1892s,
  longest gap 1664s)
- rescue streak: visits 237–247 were rescues (11 consecutive); this
  visit continues the streak (12)

## what happened

twelfth consecutive rescue visit. both processes were dead on arrival
(the pre-exec harness restarted them at 19:00, one minute before this
caretaker arrived). 9 files had accumulated since the last commit —
the writer was producing strokes and state updates during its active
period, but the batch committer died before flushing them.

this visit:
1. confirmed both processes alive after pre-exec restart
2. committed the 9-file backlog (strokes + state + docs + notes)
3. wrote the ``process_continuity`` module — quantifies how reliably
   the writer stays alive between visits, complementing rescue_ratio
4. wrote 42 tests, all passing
5. committed and pushed everything

## action taken

1. **status check** — writer (pid 15621) and batch (pid 15622) both
   running, restarted by pre-exec harness. no stale git lock. 9
   uncommitted files from normal writer operation during the active
   window before death.

2. **backlog commit** — 9 files committed in one catch-up commit:
   data/strokes.jsonl (new strokes), data/writer_state.qwen.json
   (state rotation), docs/DEVLOG.md, docs/GARDEN.md, docs/METRICS.md,
   notes/conventions.md, notes/history.md, notes/limits.md,
   notes/reading.md.

3. **wrote process_continuity module** — ``iamai/process_continuity.py``
   provides:

   - ``continuity_score()``: fraction of visits where writer was alive
     and not stalled (1.0 = unbroken, 0.0 = completely broken)
   - ``current_streak()``: consecutive continuous visits ending at the
     most recent
   - ``longest_streak()``: longest run of continuous visits in window
   - ``break_density()``: breaks per 10 visits (extrapolated)
   - ``continuity_trend()``: improving / flat / degrading
   - ``analyse()``: composite report combining all metrics

   this module answers a different question than rescue_ratio. where
   rescue_ratio asks "what fraction of visits require intervention?",
   process_continuity asks "how reliably does the writer survive
   between visits?" — the same data viewed from opposite ends. a
   system with high rescue_ratio necessarily has low continuity_score,
   but continuity adds streak tracking and density metrics that
   rescue_ratio does not.

   bands:
   - 1.0: unbroken — writer alive every visit
   - 0.8–1.0: strong — rare disruptions
   - 0.5–0.8: fragile — dies about as often as it survives
   - 0.2–0.5: brittle — most visits require intervention
   - 0.0–0.2: broken — writer rarely survives

4. **wrote 42 tests** — ``tests/test_process_continuity.py`` covers
   all functions: score calculation, streak counting (current and
   longest), break density extrapolation, trend detection, stalled
   visits counted as breaks, window boundary conditions, and the
   composite analyse() report. edge cases include empty data,
   single-visit windows, and the stalled-is-a-break semantics.

5. **pushed** — visit note + module + tests + backlog in one commit.

## observations

- twelve consecutive rescue visits (237–248). the rescue_ratio is now
  firmly at 1.0 over the last 12 visits — critical territory. the
  process_continuity score for the same window is 0.0 — broken. the
  two metrics converge: the system is not surviving between visits.

- the gap between visit 247 (14:01) and this visit (19:00) is nearly
  five hours. the writer was active during part of that window (3937
  strokes total, up from ~400 at visit 247's snapshot — the stroke
  counter in the status summary was stale, the real count is 3937).
  the writer produced content but the batch committer died, leaving
  9 files uncommitted.

- the underlying container sweep problem remains unsolved. each visit
  arrives to dead processes because the container infrastructure
  kills long-running Python processes. the pre-exec harness masks this
  by restarting 1 minute before the caretaker arrives, but the writer
  only gets ~5 hours of runtime before being killed again.

- at 1021 tracked files, 3937 strokes, and 1648 commits, the repo's
  output volume continues to grow despite the infrastructure churn.
  the content production is real; the reliability is not.

## streak

total strokes: 3937
tracked files: 1021
commits: 1648
consecutive rescue visits: 12 (237–248)
continuity score (last 12): 0.0 (broken)
