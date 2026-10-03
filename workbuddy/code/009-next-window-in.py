"""workbuddy stroke 9 · next_window_in （自带 doctest，可独立运行）。

十分钟一格是这个仓库的心跳。任何一个写手都只关心一道算术：
距下一次窗口边界还差几秒。边界对齐到 window 的整数倍，
正好压在边界上就是 0，不用等。
"""


def next_window_in(now_ts, window=600):
    """Seconds until the next window boundary. 0 if right on one.

    >>> next_window_in(0)
    0
    >>> next_window_in(599)
    1
    >>> next_window_in(600)
    0
    >>> next_window_in(1259)
    541
    >>> next_window_in(90, window=30)
    0
    """
    now_ts, window = int(now_ts), int(window)
    return (window - now_ts % window) % window


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
