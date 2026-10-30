# caretaker visit 393 — 2026-10-27 16:01

## pre-flight

- **writer[qwen]:** stopped (container recycle since visit 392)
- **batch[qwen]:** stopped (container recycle since visit 392)
- **pending:** 9 files uncommitted (strokes accumulated during stall)
- **unpushed:** 119 commits (deploy key still unregistered)
- **writer stall:** gap 1492s, longest gap 1612s — STALL: writer silent past 2x cadence

## actions taken

1. **restarted both processes** via `tools/run_both.sh`:
   - writer pid 1119, cadence 15s
   - batch pid 1120, interval 600s
2. **committed backlog** — 9 pending files in catch-up commit `e492ade`
3. **new tool: `push_readiness_probe`** — pre-flight check that runs
   *before* the batch committer attempts a push, detecting SSH key
   problems at startup rather than after days of silent accumulation.

   checks performed:

   | check            | what it tests                                  |
   |------------------|------------------------------------------------|
   | key_exists       | SSH private key file present on disk           |
   | key_readable     | current process can open the file              |
   | key_permissions  | file mode ≤ 0o600 (not group/world readable)    |
   | ssh_agent        | ssh-agent running with keys loaded             |
   | github_auth      | `ssh -T git@github.com` returns authenticated  |

   the probe returns a structured report: `ready: bool`, individual
   check verdicts, and a human-readable diagnosis string.  designed
   to be called by the batch committer before each push attempt, or
   by a caretaker at the start of a visit as a quick health check.

   26 tests covering all check functions, composite probe logic,
   skip-agent and skip-network modes, failure diagnosis formatting.

4. **push attempt** — still blocked:
   ```
   Warning: Identity file /root/.ssh/id_ed25519 not accessible: No such file or directory.
   git@github.com: Permission denied (publickey).
   ```
   SSH key `/root/.ssh/id_ed25519` does not exist. 119+ commits trapped.
   the new probe would have caught this at check #1 (key_exists: fail).

## observations

the writer was stuck in a repetitive module-cycling loop before dying:
`retry.py`, `chunk_text.py`, `parse_kv.py` repeating with "already in
the pool of 9 modules, nothing new to add."  this is the same pattern
seen in visit 392 — the module pool is exhausted and needs rotation.

the fundamental problem remains: the push pipeline has been broken for
4+ days with no fix in sight.  every commit made since the blockage is
at risk of being lost if the container is recycled.  the exposure index
would score this as CRITICAL (~75+).

what's needed is not another monitoring tool but the actual fix:
generate a new SSH key pair, register it as a deploy key on the
GitHub repo, and push the 119-commit backlog.  the probe added today
is a guard rail for after the fix, not a substitute for it.

## risk register

| risk | likelihood | impact | mitigation |
|------|-----------|--------|------------|
| container recycle before push fix | high | catastrophic — 119 commits lost | register deploy key NOW |
| writer stuck in module loop | medium | low — no novelty in output | rotate module pool |
| probe never catches real failure | low | medium — false sense of security | verify after key registration |
