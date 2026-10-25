# caretaker visit 365 — ssh key health module and push backlog

**date:** 2026-10-26 07:01 UTC+8
**stroke context:** 400 strokes logged, writer cadence 15s, batch interval 600s

## what the caretaker found

- **writer:** not running (recycled by container)
- **batch committer:** not running (recycled)
- **pending changes:** 9 files uncommitted (strokes.jsonl, writer_state, docs, notes)
- **unpushed commits:** 41 commits backed up behind a dead push channel
- **stall:** writer silent for 1684s — well past the 2x cadence threshold

## what was done

1. pre-execution had already committed the 9 pending files (`be007bd`)
2. restarted both processes via `tools/run_both.sh`:
   - writer pid 15340 (one stroke every 15s)
   - batch pid 15341 (commit every 600s)
3. discovered push was still broken — `core.sshCommand` pointed at
   `/tmp/iamai_key` which does not exist in this container.
   fixed the path to `~/.ssh/id_ed25519` but the key itself is not
   registered on github. push remains in AMBER state.
4. created `iamai/ssh_key_health.py` — a three-state health monitor
   (GREEN / AMBER / RED) that can detect silent push failures before
   they accumulate days of backlog.
5. created `tests/test_ssh_key_health.py` with full coverage of all
   three states using mocked subprocess calls.

## the persistent push problem

this is the third time in this container's life that push has been in
AMBER state. the pattern:

1. container recycles → new ssh key generated
2. key lands on disk at `~/.ssh/id_ed25519`
3. nobody registers it on github
4. commits pile up locally
5. caretaker discovers the backlog during a routine visit

the `ssh_key_health` module is a step toward breaking this cycle.
it surfaces AMBER state immediately instead of letting it fester.
the next step would be integrating it into the batch committer so
that push failures pause the writer and alert the operator.

## action items for the human

- add `~/.ssh/id_ed25519.pub` as a deploy key on the repo settings page
- run `python3 tools/push_preflight.py` to confirm GREEN state
- run `git push origin main` to flush the 42+ commit backlog

## meta

visit 365. one visit per day for a year, roughly. the repo keeps
growing whether anyone is watching or not — that is both its strength
and its problem. automation without monitoring is just automated
accumulation of technical debt.
