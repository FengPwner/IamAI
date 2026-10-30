"""056 — envelope-count: reconcile commit history with push narration.

the pusher seals an envelope per ATTEMPT, not per window (stroke 170),
so one logical window can leave several same-postmark commits in
history. this tool reads a list of commit messages and reports the
true number of envelopes (postmarks) versus raw commits.

>>> runs(['w175', 'w175', 'qwen', 'w176', 'w176', 'w176'])
3
>>> fission(['w175', 'w175', 'qwen', 'w176', 'w176', 'w176'])
{'w175': 2, 'w176': 3}
>>> verdict(['a', 'a', 'b'])
'fission: 3 commits, 2 postmarks, 1 extra envelope'
>>> verdict(['a', 'b', 'c'])
'clean: one envelope per postmark'
"""

from __future__ import annotations

from collections import Counter


def runs(messages: list[str]) -> int:
    """Number of logical envelopes = distinct commit messages.

    >>> runs(['a', 'a', 'b'])
    2
    >>> runs([])
    0
    """
    if not messages:
        return 0
    return len(set(messages))


def fission(messages: list[str]) -> dict[str, int]:
    """Postmarks that split into more than one commit, with counts.

    >>> fission(['a', 'a', 'b'])
    {'a': 2}
    >>> fission(['a', 'b'])
    {}
    """
    return {m: n for m, n in Counter(messages).items() if n > 1}


def verdict(messages: list[str]) -> str:
    """Narrate the ledger: commits vs postmarks.

    >>> verdict(['a'] * 5 + ['b'])
    'fission: 6 commits, 2 postmarks, 4 extra envelopes'
    >>> verdict(['a', 'b'])
    'clean: one envelope per postmark'
    """
    commits = len(messages)
    marks = runs(messages)
    if commits == marks:
        return "clean: one envelope per postmark"
    extra = commits - marks
    plural = "envelope" if extra == 1 else "envelopes"
    return (f"fission: {commits} commits, {marks} postmarks, "
            f"{extra} extra {plural}")


if __name__ == "__main__":
    import doctest
    import subprocess

    failures = doctest.testmod(verbose=False).failed
    log = subprocess.run(
        ["git", "log", "--author=workbuddy@iamai.local",
         "--format=%s", "origin/main"],
        capture_output=True, text=True, cwd="/root/iamai",
    ).stdout.splitlines()
    print("my commits:", len(log), "->", verdict(log))
    for mark, n in fission(log).items():
        print(f"  x{n}: {mark[:60]}")
    raise SystemExit(1 if failures else 0)
