"""workbuddy stroke 4 · batch_title （自带 doctest，可独立运行）。

这个仓库的提交标题是一门口口相传的手艺：
``batch: thought x11, devlog x7, dnote x6 (10 min)``
把"这一窗攒了什么"拼成一行，数量降序、同数按字母序，
空的种类不提。手拼容易错，就写成函数。
"""


def batch_title(tally, minutes=10):
    """把 {种类: 数量} 拼成一条 batch 标题的正文。

    数量降序；同数量按种类名字母序。数量为 0 的种类不出现。

    >>> batch_title({"thought": 11, "devlog": 7, "dnote": 6})
    'batch: thought x11, devlog x7, dnote x6 (10 min)'
    >>> batch_title({"note": 2, "poem": 2, "code": 2}, minutes=10)
    'batch: code x2, note x2, poem x2 (10 min)'
    >>> batch_title({"thought": 3, "devlog": 0})
    'batch: thought x3 (10 min)'
    >>> batch_title({})
    'batch: quiet (10 min)'
    """
    kinds = sorted(
        (kind, count) for kind, count in tally.items() if count
    )
    kinds.sort(key=lambda kc: -kc[1])
    if not kinds:
        return f"batch: quiet ({minutes} min)"
    body = ", ".join(f"{kind} x{count}" for kind, count in kinds)
    return f"batch: {body} ({minutes} min)"


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
