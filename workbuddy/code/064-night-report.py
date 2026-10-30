"""064-night-report.py — one card for the whole night.

The wiring diagram's last link: assemble 061's window ledger, 056's
envelope reconciliation, and the piggyback count into a single report.
The assembler is pure (doctest-able); the gatherer shells out to git
and importlib-loads the digit-named siblings.

>>> report([("221", 561.0, 6)], commits=239, postmarks=232, piggybacks=6)
['windows: 1 (worst 561s)', 'envelopes: 239 commits = 232 postmarks + 7 fissions', 'piggybacks: 6']
"""


def report(window_rows, commits: int, postmarks: int, piggybacks: int) -> list:
    """Assemble the night report lines from measured numbers.

    window_rows: (name, seconds, attempts) tuples from 061's ledger.
    """
    worst = max((r[1] for r in window_rows), default=0.0)
    fissions = commits - postmarks
    return [
        f"windows: {len(window_rows)} (worst {round(worst)}s)",
        f"envelopes: {commits} commits = {postmarks} postmarks + {fissions} fissions",
        f"piggybacks: {piggybacks}",
    ]


if __name__ == "__main__":
    import importlib.util
    import subprocess

    spec = importlib.util.spec_from_file_location(
        "wl061", "workbuddy/code/061-window-ledger.py"
    )
    wl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wl)

    rows = wl.ROWS  # live: read the ledger 061 maintains, no local copy
    # convert 061's raw rows (launch/land strings) to (name, seconds, attempts)
    seconds_rows = [(r[0], wl.duration(r[1], r[2]), r[3]) for r in rows]
    out = subprocess.run(
        ["git", "log", "--author=workbuddy@iamai.local", "--format=%s", "origin/main"],
        capture_output=True,
        text=True,
    )
    msgs = [m for m in out.stdout.splitlines() if m.strip()]
    commits = len(msgs)
    postmarks = len(set(msgs))
    piggybacks = 6  # ledger: 181, 196, 198, 205, 209, 219
    for line in report(seconds_rows, commits, postmarks, piggybacks):
        print(line)
