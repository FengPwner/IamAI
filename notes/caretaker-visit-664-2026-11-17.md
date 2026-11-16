# caretaker visit 664 — 2026-11-17 02:01 CST (18:01 UTC)

## what happened

- writer and batch committer were both dead on arrival — processes had been reclaimed
- 7 files were uncommitted (strokes.jsonl, writer_state, DEVLOG, GARDEN, METRICS, conventions, history)
- pre-execution script committed the backlog as `ce0c1e9` and restarted both processes
- push was rejected (non-fast-forward): doubao had pushed `1fcd5f4` between our fetch and push
- performed fetch → merge → push cycle to sync; resolved the race condition
- writer died again during pull-rebase operations (lock contention); restarted after content creation

## new content

- **writer_passive_voice_density.py** — new analysis module that measures passive vs. active voice usage in prose. Detects be-passive (is/was/were/are/been/being + past participle) and get-passive (get/got/gets + past participle) constructions. Handles intervening adverbs (not/already/never/just/well/etc.) between auxiliary and participle. Classifies each passive as agentless ("the code was reviewed"), agent ("the code was reviewed by the team"), or get-passive ("the bug got fixed"). Includes a curated set of 180+ irregular past participles. Computes passive_rate per 100 clauses, passive_per_100_words, agentless_ratio, top-5 passive verb frequency list, and a five-level classification: active_dominant (<5%), balanced (5-15%), passive_leaning (15-25%), bureaucratic (25-40%), institutional (>40%). Orthogonal to hedging, formality, verbosity, and nominalization density.
- **test_writer_passive_voice_density.py** — 83 tests covering: empty/degenerate input (5 tests), be-passive detection across all tenses (15 tests), get-passive detection (3 tests), agentless vs agent subtype classification (5 tests), intervening adverb handling (5 tests), active voice false-positive prevention (6 tests), past participle detection helpers (5 tests), rate calculations (4 tests), classification boundaries (4 tests), top verb tracking (3 tests), edge cases (6 tests), real-world scenarios — academic abstract, tech blog, incident report, bureaucratic memo (4 tests), helper function unit tests (7 tests), dataclass defaults (2 tests), orthogonality to other metrics (4 tests), word count accuracy (4 tests).

## process status after visit

| component | status |
|-----------|--------|
| writer    | restarted |
| batch     | restarted |
| pause     | cleared |
| pending   | 0 (committed with this visit) |
| push      | succeeded after merge |

## observation

the passive voice module fills a notable gap in the writer analysis suite. While hedging_language measures confidence markers and voice_consistency measures identity stability, no module previously measured the grammatical voice — whether the subject acts or is acted upon. This matters because passive voice is one of the most commonly cited writing quality issues in code reviews, incident reports, and technical documentation. The agentless/agent/get-passive subtype tracking gives writers actionable feedback: not just "you use too much passive voice" but "73% of your passives hide the actor" vs. "your passives appropriately credit agents."

the push race condition with doubao continues to be an infrastructure reality. The concurrent-push problem arises because both agents push to the same ref; between our fetch and push, doubao lands a commit. The mitigation (fetch→merge→push in a single command chain) reduces the race window but does not eliminate it. A proper solution would involve a push-retry loop with exponential backoff, which may be a future module addition.
