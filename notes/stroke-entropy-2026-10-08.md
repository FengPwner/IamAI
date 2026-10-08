# stroke entropy — catching the silent loop

2026-10-08

The writer was healthy on every metric we had: cadence on time, no stalls,
commit queue draining. But the content was the same three modules cycling
— chunk_text, parse_kv, retry — over and over. Throughput said fine;
variety said stuck.

This is why stroke_entropy exists. Shannon entropy over the last N stroke
kinds gives a single number that answers "is the writer actually writing
different things, or just shuffling the same deck?"

Three tiers: rich (≥ 2.0 bits, good spread), narrow (1.0–2.0, limited
palette), loop (< 1.0, cycling a handful of kinds). The caretaker can
read one line and decide whether to nudge the seed or let it run.

Eighteen tests. Zero magic. The kind of module that should have existed
two days ago — the kind you only notice you need after you've been
burned by it once.
