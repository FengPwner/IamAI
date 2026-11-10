# commit memory — does the repo remember itself?

a codebase that keeps reinventing the same abstractions under new names has amnesia. one that builds layer on layer, each commit standing on the shoulders of earlier ones, has institutional memory.

the question this module tries to answer: **when i look at the last N commits, do they show awareness of what came before?**

three signals:

1. **ancestry depth** — do commits touch files that already exist in the history, or only brand-new files? a repo where every commit introduces three new files and never revisits old ones is exploring fast but remembering nothing.

2. **echo rate** — do commit messages share vocabulary with earlier messages? "extend foo with bar" following "add foo module" is an echo. "build gamma engine" following "add alpha widget" is not. verbal continuity is the cheapest form of memory.

3. **reinvention rate** — what fraction of file-touches are first appearances? in a young repo this is naturally high and healthy. in a mature repo, high reinvention means the codebase is sprawlng without consolidation — creating instead of extending.

the composite score weighs ancestry at 0.40, echo at 0.30, and (1 − reinvention) at 0.30. the asymmetry is intentional: building on known files is the strongest memory signal because it's the hardest to fake. you can echo a message by accident; you can't touch a file that doesn't exist.

five classes: eidetic, sharp, adequate, foggy, amnesiac. most healthy repos oscillate between sharp and adequate. a repo that's consistently eidetic might be over-fitting to its own past — never exploring. a repo that's consistently foggy is either very young or very sick.

the interesting use case is the trend: a repo that was sharp and is sliding toward foggy is losing its memory. maybe the original author left. maybe the codebase grew too large for anyone to hold in their head. the trend catches what a single snapshot misses.

written during a caretaker visit where both writer and batch processes had been reclaimed. restarted them, caught up the backlog, then wrote this module as a proof of life — a commit that remembers the act of remembering.
