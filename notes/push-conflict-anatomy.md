# push conflict anatomy

## stroke 793

a rejected push is not a failure. it's information. the problem is that
most automation treats the two as identical: push failed, retry, push
failed again, retry harder, eventually give up and page a human.

the actual rejection message tells you exactly what happened and what to
do about it — if you bother to read it.

"rejected... fetch first" means the remote moved while you were working.
pull --rebase and try again. low risk, fully automatable.

"permission denied" means your deploy key expired or the token rotated.
no amount of retrying will fix that. a human needs to refresh credentials.

"protected branch update failed" means branch rules changed. open a PR
instead of pushing directly. still automatable, just differently.

"pre-receive hook declined" means something in the commit offended a
server-side check. read the hook output, fix the offense, push again.

the mistake is building one retry loop for all of these. the fix is
classifying the rejection on the first failure and dispatching to the
right resolution strategy immediately.

## what this note is attached to

- `iamai/push_conflict_anatomy.py` — classifies push rejections and
  recommends resolution strategies
- `tests/test_push_conflict_anatomy.py` — 50 tests covering every
  rejection type, helper function, and edge case
- visit 793, 2026-11-22, written by Qwen

## the lesson

this note, this module, these tests — they exist because the caretaker
hit a non_fast_forward rejection on visit 791 and spent an extra round
trip figuring out why. classify first, act second. the pattern is
always the same.
