# visit 788 — test coverage for push_diag + ssh_key_mismatch

2026-11-22 13:02 CST. human-requested caretaker check. both processes
found dead on arrival (overnight stall pattern continues, gap ~2986s,
consistent with visits 782–787). backlog of 7 uncommitted files flushed
as be2488d, processes restarted (writer pid 6424, batch pid 6425),
push confirmed to main.

## what this visit adds

two new test files covering the last two modules in `iamai/` that had
zero test coverage. after this visit, every module in the core package
has at least one dedicated test file.

### test_push_diag.py (37 tests)

`push_diag.py` is the quick-response diagnostic the caretaker calls
when push fails. it checks the entire push pipeline — key file, permissions,
pubkey, ssh connectivity, unpushed backlog — and produces an actionable
fix hint. speed matters here: the caretaker calls this during every
failed push, so it needs to be correct and fast.

test areas:

1. **PushState enum** — all seven states exist, string behaviour,
   value lookup.

2. **PushDiagnosis dataclass** — field access, asdict serialization,
   default workspace key fields.

3. **_run helper** — success path, timeout handling, OS error.

4. **_check_key_file** — missing file, correct permissions (0o600),
   open permissions (0o644).

5. **_get_fingerprint** — missing pubkey, valid key parsing, keygen
   failure.

6. **_keys_match** — both missing, one missing, matching content,
   different content.

7. **generate_fix_hint** — every PushState produces an actionable hint:
   HEALTHY shows "healthy", NO_KEY with workspace key offers cp command,
   NO_KEY without workspace key suggests ssh-keygen, BAD_PERMS shows
   chmod 600, NO_PUBKEY shows ssh-keygen -y, UNREGISTERED links to
   deploy key settings, NETWORK suggests ping/curl, UNKNOWN recommends
   manual diagnostics.

8. **format_report** — healthy report shows [OK] and PASS, failed
   report shows [!!] and FAIL with commit count and age, workspace key
   display with MATCHES/DIFFERS.

9. **diagnose integration** — mocked full pipeline for HEALTHY, NO_KEY,
   BAD_PERMS, UNREGISTERED, and NETWORK states. temp files with real
   chmod to verify permission checking end-to-end.

10. **Edge cases** — every fix hint has minimum length, PushDiagnosis
    survives json roundtrip.

### test_ssh_key_mismatch.py (31 tests)

`ssh_key_mismatch.py` separates "never registered" from "key was
swapped" — a critical distinction for the caretaker because the
remediation differs completely. UNREGISTERED means "add the pubkey
to github." MISMATCH means "the container recycle replaced your key
with a stale backup."

test areas:

1. **MismatchKind enum** — all five kinds exist, string behaviour,
   value uniqueness.

2. **MismatchResult dataclass** — default fields, auto-timestamp via
   __post_init__, explicit timestamp, fingerprint propagation.

3. **_extract_fingerprint** — missing key, valid key parsing, keygen
   failure, timeout, short output.

4. **_probe_github** — success (rc=0), permission denied, timeout,
   OS error.

5. **_find_local_key** — no keys found, readable key, skips open
   permissions, returns first valid, skips invalid then finds valid,
   all nonexistent.

6. **_has_push_history** — has history, no history (empty output),
   git failure, OS error.

7. **classify_key_failure** — no key → UNKNOWN, key ok → OK,
   permission denied + no history → UNREGISTERED, permission denied +
   history → MISMATCH, unexpected response → UNKNOWN, no repo_path
   skips history check.

8. **Edge cases** — JSON serialization, fingerprint None propagation,
   enum value uniqueness.

## test gap closed

after this visit, zero modules in `iamai/` remain without tests.
the test gap that was four modules wide at visit 785 is now fully
closed:

| visit | untested modules remaining |
|-------|---------------------------|
| 785   | 4 (stall_loss + 3 others) |
| 786   | 4 (added restart_settling)|
| 787   | 2 (push_diag, ssh_key)    |
| 788   | 0                         |

total new tests this visit: 68.

## overnight stall continues

the stall pattern holds with remarkable consistency:

| visit | gap (s) | severity  |
|-------|---------|-----------|
| 782   | ~2978   | moderate  |
| 783   | ~2978   | moderate  |
| 784   | ~2640   | moderate  |
| 785   | ~2945   | moderate  |
| 786   | ~2915   | moderate  |
| 787   | ~3000   | moderate  |
| 788   | ~2986   | moderate  |

mean ~2920s (48.7 min), std dev ~115s. this is clearly a fixed idle
timeout in the hosting environment. the standard restart-and-resume
pattern continues to work without intervention.

## process status

writer: running, cadence 15s (pid 6424).
batch: running, interval 600s (pid 6425).
tree clean, push confirmed.
stroke count: 400+ per kind.
tracked files: 2611.
