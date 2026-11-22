# visit 800 — caretaker_autorecover: single-command crash recovery

2026-11-22 23:05 CST. human-requested caretaker check.

## context

visits 798 and 799 each added one piece of the recovery puzzle:
death clock (diagnostic) and push guard (recovery). visit 799's
observation was explicit — "the next logical step is a single
caretaker script that runs both in sequence — detect death, record
it, recover push, resume cadence."

this is that script. visit 800.

## what this visit adds

### tools/caretaker_autorecover.py

one entry point that runs the full recovery sequence:

1. **probe** — read pid files, check liveness via os.kill(pid, 0).
2. **record deaths** — for each dead process, append to death_clock.json.
3. **restart** — invoke run_both.sh (only if something was dead).
4. **push recovery** — run guarded_push() to flush unpushed commits.
5. **report** — return a structured RecoveryReport dataclass.

CLI modes:
- `--probe-only`: check liveness, exit 2 if anything dead, no action.
- `--dry-run`: show what would happen without doing it.
- `--json`: output the report as JSON for scripted consumption.
- default: full recovery, exit 0 on success, 1 on failure.

design choices:
- lazy imports of process_death_clock and push_guard — the module
  works even if either dependency is missing (records empty list
  or returns push error).
- re-probes after restart so the report reflects post-recovery state.
- RecoveryReport.recovered is a computed property, not a field:
  it considers writer alive, batch alive, push ok, and no errors.
- push is always attempted even if both processes were alive on
  probe — there may be unpushed commits from before the check.

### tests/test_caretaker_autorecover.py

22 tests covering:

- RecoveryReport: recovered/not-recovered under 7 conditions
  (both alive, writer dead, batch dead, push failed, push ok,
  errors present, push skipped).
- _read_pid: valid, missing, empty, non-numeric pid files.
- _is_alive: None, nonexistent, current process.
- probe: both alive, both dead, missing pid files.
- _record_deaths: both dead, one dead, both alive, import failure.
- _restart: success, failure, missing script, timeout.
- autorecover: probe-only, full recovery from dead, already alive
  skips restart, restart failure reports error, push failure
  reports error, dry run.

## process state at visit time

```
writer[qwen]: running pid 6361
batch [qwen]: running pid 6362
pending: 2 files (normal writer drift)
tracked: 2641 files
strokes: 6951+ lines in strokes.jsonl
```

## observation

visit 800 is a milestone — three digits of caretaker attention.
the pattern has been convergent: each visit adds a diagnostic,
then the next visit composes diagnostics into recovery. death
clock → push guard → autorecover. the next step is not another
tool but a policy: when should autorecover run automatically
(from commit_batch.py's health check) versus when should it wait
for a human? that decision belongs to visit 801.
