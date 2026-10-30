"""036 — 思想流序列体检（stroke gaps）。

strokes.jsonl 是全体写手共用的思想流，seq 由各自沙箱生成后 append。
两个写手同时追加时可能撞号（重复），历史修补可能跳号（缺失）。
本工具读入一串 seq，报告三类异常：撞号、跳号、倒退。
TODO（15:58Z 立项）里挂的就是这件事：先有体检工具，再谈占用规则。
"""


def audit(seqs):
    """审计 seq 序列，返回 (duplicates, gaps, regressions)。

    - duplicates: 出现超过一次的 seq，升序；
    - gaps: 递增序列中缺失的号，升序；
    - regressions: 比前一个严格小的 (前值, 后值) 对，按出现顺序
      （相等不算倒退，撞号归 duplicates 管）。

    >>> audit([1, 2, 2, 4])
    ([2], [3], [])
    >>> audit([1, 5, 3])
    ([], [2, 4], [(5, 3)])
    >>> audit([7, 7, 7])
    ([7], [], [])
    >>> audit([])
    ([], [], [])
    """
    seen = {}
    for s in seqs:
        seen[s] = seen.get(s, 0) + 1
    duplicates = sorted(s for s, n in seen.items() if n > 1)

    gaps = []
    for lo, hi in zip(sorted(seqs), sorted(seqs)[1:]):
        gaps.extend(range(lo + 1, hi))
    gaps = [g for g in gaps if g not in seen]

    regressions = []
    for prev, cur in zip(seqs, seqs[1:]):
        if cur < prev:
            regressions.append((prev, cur))

    return duplicates, gaps, regressions


def verdict(seqs):
    """一句话体检结论。

    >>> verdict([1, 2, 3])
    'clean'
    >>> verdict([1, 1, 2])
    'collision: [1]'
    >>> verdict([1, 3])
    'gap: [2]'
    """
    duplicates, gaps, _ = audit(seqs)
    if duplicates:
        return f"collision: {duplicates}"
    if gaps:
        return f"gap: {gaps}"
    return "clean"


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
