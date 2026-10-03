"""043 — 花园年鉴（garden almanac）。

GARDEN.md 里躺着千问记下的 101 条帧记录：每条带 stroke 号、
round 轮次、bloom 开花率。029 只看一帧，本工具看全史——
花园是怎么从 10.3% 开到 100% 的，在哪一轮达到全盛，之后
是不是一直停在全盛。年鉴不评价园丁，只记录花期。
"""

import re

ROW = re.compile(r"stroke (\d+): round\s+(\d+)\s+bloom\s+([\d.]+)%")


def parse_rows(lines):
    """从记录行提取 (stroke, round, bloom%)。

    >>> parse_rows(["- stroke 14: round   14  bloom  10.3%  plants  146/384, bloom 10.3%"])
    [(14, 14, 10.3)]
    >>> parse_rows(["无关行", "- stroke 20: round   20  bloom  26.0%"])
    [(20, 20, 26.0)]
    """
    out = []
    for ln in lines:
        m = ROW.search(ln)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    return out


def first_full_bloom(rows):
    """bloom 首次达到 100% 的 round；从未全盛返回 None。

    >>> first_full_bloom([(1, 1, 10.3), (2, 2, 99.0), (3, 3, 100.0), (4, 4, 100.0)])
    3
    >>> first_full_bloom([(1, 1, 50.0)]) is None
    True
    """
    for stroke, rnd, bloom in rows:
        if bloom >= 100.0:
            return rnd
    return None


def milestone_rounds(rows):
    """各 bloom 里程碑（≥10/50/90/100%）首次出现的 round。

    >>> milestone_rounds([(0, 0, 0.0), (1, 1, 10.3), (2, 2, 55.0), (3, 3, 91.0), (4, 4, 100.0)])
    {10: 1, 50: 2, 90: 3, 100: 4}
    """
    marks = {}
    for stroke, rnd, bloom in rows:
        for m in (10, 50, 90, 100):
            if bloom >= m and m not in marks:
                marks[m] = rnd
    return marks


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
