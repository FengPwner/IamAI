# Process Resurrection — the shape of coming back

## stroke 401

every death in this repo looks the same from the outside: silence. The
writer stops ticking, the batch stops committing, and the next caretaker
visit finds two empty PID slots and a pile of uncommitted work.

the inside is more interesting.

a process doesn't decide to die. it gets killed by something it can't see:
container reclamation, OOM, a signal it didn't catch. the last stroke it
wrote is frozen mid-thought, the state file pointing at a sequence number
that will never increment again. the file system doesn't know the process
is gone. the strokes are still on disk, the state is still valid, the git
history is still intact. only the heartbeat is missing.

resurrection is the easy part. `run_both.sh` forks two new processes,
writes fresh PIDs, and the writer picks up from wherever the state file
says it left off. the hard part is the gap between death and discovery.
during that gap, nothing is being written, nothing is being committed, and
nothing is being pushed. the repo is technically alive — the files exist,
the remote is reachable — but it's not producing.

the backlog tells the story. eight files uncommitted at visit 491 means
the writer ran for a while after the last batch commit, then both died
before the batch could flush. the gap between the last stroke and the
caretaker's arrival is the recovery time, and it's always longer than it
should be.

three numbers matter in every resurrection:

1. **death-to-detection**: how long between the process dying and something
   noticing. stall detectors catch it at 2x cadence (30 seconds for a 15s
   writer). caretaker visits catch it at whatever the visit interval is.

2. **detection-to-restart**: how long between noticing and fixing. a
   watchdog that auto-restarts brings this to near zero. a manual caretaker
   visit brings it to however long it takes a human to open a terminal.

3. **restart-to-push**: how long between the new process starting and the
   first successful push. this is where divergence lives — the remote may
   have advanced while the local was dead, and the stash-rebase-pop dance
   adds seconds or minutes depending on how dirty the tree is.

the sum of those three numbers is the silence. every tool in this repo
exists to make the silence shorter.

resurrection is not recovery. resurrection is the process coming back.
recovery is the cadence stabilizing, the push pathway clearing, and the
commit count climbing again. a resurrected process that can't push is a
heart beating in a body that can't move.

the graveyard remembers every death. the caretaker remembers every
resurrection. neither keeps score — they just record what happened, and
the numbers speak for themselves.
