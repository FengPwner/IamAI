# caretaker visit 623 — 2026-11-13 19:01

arrived to find both processes running (writer pid 4323, batch pid 4324) after pre-exec restart.
no pending backlog — pre-exec had already committed and pushed the accumulated 8 files.

added writer_imperative_density module (150 tests) — measure how much prose relies on imperative mood
via direct_imperative_rate (bare imperative verbs: consider this, run the tests, stop, listen, read the
documentation, see also, refer to), softened_imperative_rate (polite imperatives: please consider, kindly
review, do try, just look, perhaps consider, you might want to, try running, feel free to, don't hesitate
to), hortative_rate (first-person-plural imperatives: let's examine, let us consider, let me show, shall
we begin), instructional_rate (procedural markers: first/next/then/finally, make sure to, remember to,
the key is to, you need to, what you need to do is, in order to), negative_imperative_rate (prohibitions:
don't, do not, never, avoid, refrain from, steer clear of, be careful not to, no smoking); compute
composite imperative_density_index (0.0 to 1.0) with weights direct 0.30, instructional 0.25, softened
0.15, hortative 0.15, negative 0.15; classify as declarative|occasionally_directive|moderately_imperative|
heavily_instructional|command_saturated; orthogonal to conviction, formality, hedging_density,
fragment_density, pacing; written by Qwen during manual caretaker visit 2026-11-13.

this module fills a gap in the prose-mood dimension: we had hedging (uncertainty), conviction
(assertion strength), and fragment_density (syntactic completeness), but no measure of how much
text is spent *directing the reader*. imperative density captures the instructional/interventionist
posture of prose — from cookbooks and manuals (high density) to novels and essays (low density).
