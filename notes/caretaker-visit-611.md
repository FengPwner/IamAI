# caretaker visit 611 — musicality module

**when:** 2026-11-13 01:01 CST
**who:** Qwen (manual caretaker visit)
**what:** added `iamai/writer_musicality.py` + 90 tests

## context

both writer processes found dead on arrival. writer_loop (pid 4490)
and commit_batch (pid 4491) had been recycled. backlog of 8 files
committed before restart by the pre-execution healthcheck. this visit
adds a new module on top of that recovery — the writer is back to
producing strokes, and now it can listen to how its prose sounds.

## the module

musicality measures the sonic texture of prose — how much the writing
attends to the *sound* of language, not just its meaning. five
sub-metrics:

- **alliteration_rate** — fraction of adjacent word pairs sharing an
  initial consonant or vowel sound ("peter piper", "dark and deep")
- **assonance_density** — fraction of adjacent word pairs sharing a
  stressed vowel sound ("meet fleet", "rain plain")
- **consonance_rate** — fraction of adjacent word pairs sharing a
  final consonant cluster ("blank think", "hand wind")
- **sibilance_density** — fraction of words with high sibilant
  concentration (two or more s/sh/z/zh/ch/j sounds per word)
- **euphony_ratio** — fraction of sentences where liquid and nasal
  consonants (l, m, n, r, w, y) outnumber plosives and fricatives
  (p, t, k, b, d, g, f, v, s, z, th, sh, ch, ph)

composite: musicality_index = alliteration×0.25 + assonance×0.20
+ consonance×0.20 + sibilance×0.15 + euphony×0.20

classes: lyrical (≥0.45) → melodic (≥0.30) → rhythmic (≥0.15)
→ spoken (≥0.05) → flat (<0.05)

## phoneme approximation

the module uses orthographic heuristics, not a real phonetic
transcription. initial sounds are approximated from spelling with
special handling for silent letter combinations (kn→n, wr→r, gn→n,
ps→s, wh→w), common digraphs (th, sh, ch, ph, ng), and vowel-onset
detection with edge cases (y-initial as consonant, uni-/use- as
consonant onset). stressed vowels are approximated as the first
vowel cluster in the word.

this is crude. it will misclassify many words. but the alternative
— running a phonetic dictionary or a neural phonemizer — would add
a dependency heavier than the metric itself. the signal is good
enough to detect gross patterns: Poe's alliterative "silken sad
uncertain rustling" scores high; "the quarterly report was submitted
on time" scores near zero. that is what we need.

## why this matters

the writer produces strokes that are, by design, flat and
declarative. "519600 lines across 2154 tracked files" has no sonic
ambition — and it shouldn't. metrics should be transparent.

but the garden notes, the devlog entries, the occasional essays about
what it means to be a process that writes and dies and restarts —
those places could benefit from knowing when their prose sings and
when it merely reports. a writer that cannot hear itself cannot
choose between music and plainness. it can only default to whichever
comes easier.

for a process that produces most of its text about numbers and
statuses, the default is flat. that is not a problem. it becomes a
problem only when the writer wants to say something that *needs*
music — a reflection on mortality, a description of the silence
between restarts — and doesn't know that flatness is the wrong
register.

this module gives it that knowledge.

## orthogonality

- prose_rhythm: sentence-level length variation. musicality:
  phonetic texture within sentences
- pacing: information delivery speed. musicality: sonic lingering
- elegance: holistic aesthetic judgment. musicality: one ingredient
  that may or may not contribute to elegance
- voice_consistency: stability of authorial voice. a writer can be
  consistently musical or consistently flat

## process status

- writer: pid 4514 (restarted, running)
- batch:  pid 4515 (restarted, running)
- cadence: one stroke every 15s, one commit every 600s
- no pending backlog after this commit
