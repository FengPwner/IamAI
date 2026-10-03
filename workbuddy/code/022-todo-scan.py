"""workbuddy stroke 25 · todo_scan （自带 doctest，可独立运行）。

TODO 页是 markdown 的 checkbox。扫一遍就知道还欠几件、
还了几件——流水页和快照页都用得上。
"""


def todo_scan(markdown: str) -> tuple[int, int]:
    """(open, done) checkbox counts. Lines like `- [ ]` and `- [x]`.

    >>> todo_scan("- [ ] a\\n- [x] b\\n- [ ] c")
    (2, 1)
    >>> todo_scan("- [X] done caps")
    (0, 1)
    >>> todo_scan("- plain item\\n- [ ] one")
    (1, 0)
    >>> todo_scan("")
    (0, 0)
    """
    open_count = done = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            open_count += 1
        elif stripped.startswith("- [x]") or stripped.startswith("- [X]"):
            done += 1
    return (open_count, done)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
