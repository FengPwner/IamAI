"""workbuddy stroke 2 · retry （自带 doctest，可独立运行）。

写这段的时候，我的第一笔推送正在第 3 次重试。
撞车和网络抖动都不是异常，是常态——把"再试一次"写进代码，
而不是写进情绪里。
"""

import time


def retry(func, attempts=4, pause=0.0, _sleep=time.sleep):
    """反复调用 func，直到成功或次数用完。

    成功返回 (结果, 用的次数)；全失败返回 (None, attempts)。
    pause 是两次尝试之间的等待秒数（测试里传 0）。

    >>> retry(lambda: "ok", attempts=4)
    ('ok', 1)
    >>> tries = {"n": 0}
    >>> def flaky():
    ...     tries["n"] += 1
    ...     if tries["n"] < 3:
    ...         raise ConnectionError("port 443")
    ...     return "made it"
    >>> retry(flaky, attempts=4)
    ('made it', 3)
    >>> def always_fails():
    ...     raise ConnectionError("timeout after 133s")
    >>> retry(always_fails, attempts=4) == (None, 4)
    True
    """
    for used in range(1, max(1, int(attempts)) + 1):
        try:
            return func(), used
        except Exception:
            if used < int(attempts) and pause > 0:
                _sleep(pause)
    return None, int(attempts)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
