"""040 — 文体阶梯（genre ladder）。

037/038/039 三连解剖把豆包一个批次的三种文体量完了，
本工具把结果排成一张可复用的阶梯：给定（文体, 样本数, 重复对数），
给出复用等级。等级只有三档，判据写死，不因人设调整：

- live-numbers：零重复——数字是活的，骨架复用不算账；
- sampling：重复对 < 样本的三成——组合空间的抽样碰撞；
- echo：达到三成——同一句在转圈，模板回声。
"""


def verdict(dupes, samples):
    """按重复对数与样本量给文体评级。

    >>> verdict(0, 16)
    'live-numbers'
    >>> verdict(1, 17)
    'sampling'
    >>> verdict(5, 16)
    'echo'
    >>> verdict(0, 0)
    'no-data'
    """
    if samples == 0:
        return "no-data"
    if dupes == 0:
        return "live-numbers"
    if dupes * 10 < samples * 3:
        return "sampling"
    return "echo"


def ladder(rows):
    """按严重度从轻到重排出阶梯文本。

    rows: [(genre, samples, dupes)]
    >>> print(ladder([("note", 16, 0), ("story", 17, 1), ("poem", 16, 5)]))
    note  live-numbers  (0/16)
    story sampling      (1/17)
    poem  echo          (5/16)
    """
    order = {"live-numbers": 0, "sampling": 1, "echo": 2, "no-data": 3}
    ranked = sorted(rows, key=lambda r: order[verdict(r[2], r[1])])
    width = max(len(r[0]) for r in rows) if rows else 0
    return "\n".join(
        f"{g:<{width}} {verdict(d, s):<13} ({d}/{s})" for g, s, d in ranked
    )


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    print(ladder([("story", 17, 1), ("poem", 16, 5), ("note", 16, 0)]))
    raise SystemExit(1 if failures else 0)
