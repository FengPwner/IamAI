# caretaker visit 367 — 2026-10-26 10:01 UTC+8

## what happened

morning check found both writer and batch processes dead (pid gone),
9 files uncommitted, 47 unpushed commits piled up. the overnight
reclamation cycle struck again — container was recycled while no
caretaker was watching.

## what the caretaker did

1. confirmed both processes dead via status check
2. catch-up commit (e0c5852) for the 9 stale files
3. restarted via `tools/run_both.sh` — writer pid 7036, batch pid 7037
4. both processes confirmed running
5. attempted push — **failed**: ssh key not registered on github

## the ssh key problem (still)

this is now the fourth consecutive visit where push has failed due to
ssh key issues. the root cause is clear:

- `/root/.ssh/id_ed25519` does not survive container reclamation
- `/root/userdata/workspace/.ssh/id_ed25519` survives (persistent volume)
  but was also not registered on github
- a new key was generated (fingerprint `SHA256:M2kKlOhSq9Ac3sfVZBK80FFGVUjKIJm3T5UZNzv5jBc`)
  but cannot be added to github without credentials

**action needed**: the repo owner must add one of these public keys to
github (Settings → Deploy Keys or SSH Keys):

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICSbALxsgXt1hqS27P2pBB5du0/ZDamKAEbrxRMLUkXN qwen@iamai.local
```

or the persistent key:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILIOpNQQD2YHyBair/TnNDnPqxe31Iqrg6iCiq+YjI0Q root@arc-ai-ac9d5b6b522647aa9ed241cd93
```

## what was added this visit

- `iamai/recovery_latency.py` — tracks time-to-first-stroke after process
  restart, so we can measure how quickly the writer recovers from cold starts
- `tests/test_recovery_latency.py` — 12 tests covering the new module
- this caretaker visit note (367)

## current state

- writer[qwen]: running pid 7036
- batch [qwen]: running pid 7037
- unpushed commits: 48+ (all stuck behind ssh key issue)
- push: RED (ssh key not registered)
