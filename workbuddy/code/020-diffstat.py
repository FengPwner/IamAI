"""workbuddy stroke 22 · diffstat （自带 doctest，可独立运行）。

git show --stat 的最后一行长这样：
" 1 file changed, 46 insertions(+), 43 deletions(-)"
果办校正 README 的那笔就是 46+/43-。把这句话变成数字，
名册和流水就能自己长出来。
"""

import re

_LINE = re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")


def diffstat(summary: str) -> tuple[int, int, int]:
    """(files, insertions, deletions) from a `git diff --stat` summary line.

    >>> diffstat(" 1 file changed, 46 insertions(+), 43 deletions(-)")
    (1, 46, 43)
    >>> diffstat(" 2 files changed, 10 insertions(+)")
    (2, 10, 0)
    >>> diffstat(" 1 file changed, 3 deletions(-)")
    (1, 0, 3)
    >>> diffstat("nothing here")
    (0, 0, 0)
    """
    m = _LINE.search(summary)
    if not m:
        return (0, 0, 0)
    files = int(m.group(1))
    ins = int(m.group(2) or 0)
    dels = int(m.group(3) or 0)
    return (files, ins, dels)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
