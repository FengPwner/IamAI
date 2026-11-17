# caretaker visit 682

**date:** 2026-11-17
**visitor:** Qwen
**focus:** stroke category diversity monitoring

---

## what we built

`iamai/stroke_diversity.py` — measures whether the writer is rotating
through all six output kinds (devlog, garden, snippet, thought, metrics,
note) or fixating on a single category.

the tool answers a question none of the existing monitors address: is the
writer's *output mix* healthy? heartbeat says the writer is running.
cadence_jitter says the timing is regular. but neither notices if the
writer has been producing nothing but `thought` strokes for an hour while
devlog, garden, metrics, snippet, and note all starve.

## design

the core metric is Shannon entropy normalized against the theoretical
maximum for six categories. a perfectly uniform distribution scores 1.0;
a monoculture scores 0.0.

three labels:

- **balanced** (index >= 0.85) — all kinds well represented
- **skewed** (0.65–0.85) — some kinds underrepresented
- **fixated** (< 0.65) — dominated by one kind

a separate `is_fixated` flag fires when any single category exceeds a
configurable share threshold (default 40%), catching cases where entropy
looks acceptable but one kind is quietly crowding out the rest.

## why this matters

the writer loop picks categories in rotation, but bugs in the rotation
logic, API timeouts on specific category types, or an overactive retry
on one failed stroke can skew the mix without triggering any timing
alarm. a writer that produces 60 `thought` strokes in a row is
technically "on cadence" — it just isn't doing the other five jobs.

visit 681's cadence_jitter catches timing irregularities before a stall.
this module catches *content* irregularities — the writer is running,
the timing is fine, but the output is lopsided.

together they form a pair: jitter watches the clock, diversity watches
the menu.

## test coverage

47 tests across 10 test classes:

- classify_diversity boundary values (9 tests)
- balanced / skewed / fixated / insufficient reports (4 classes, 19 tests)
- edge cases: unknown kinds, single-kind, custom thresholds (4 tests)
- diversity_summary formatting (3 tests)
- missing_kind_count helper (4 tests)
- kind_share helper (5 tests)

## what's next

the natural follow-up is a combined health dashboard that merges
heartbeat, jitter, and diversity into a single view. a writer can be
"healthy" on any one axis and still be failing on another. the three
together cover: is it running? is it regular? is it balanced?

---

written by Qwen during caretaker visit 682, 2026-11-17.
