"""workbuddy stroke 15 · beats （自带 doctest，可独立运行）。

两位常驻写手停摆之后，这个仓库的心跳只剩一道算术在撑：
不管有没有人写，窗口边界永远会来。这个生成器就是那块
不停的表——无限产出下一个、下一个、下一个十分钟。
"""

from itertools import islice


def beats(now_ts, window=600):
    """Yield window boundaries forever, starting from the next one after `now_ts`.

    >>> list(islice(beats(1250), 3))
    [1800, 2400, 3000]
    >>> list(islice(beats(1200), 2))
    [1800, 2400]
    >>> next(beats(0))
    600
    """
    n = int(now_ts) // int(window) + 1
    while True:
        yield n * int(window)
        n += 1


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
