"""workbuddy stroke 30 · window_clock （自带 doctest，可独立运行）。

把 009 的"还差几秒"和 guoban 008 的"在哪个窗口"合到一张表上：
写手抬头看钟，需要的其实是两个数。
"""


def window_clock(now_ts, window=600):
    """(window_index, seconds_to_next_boundary) for `now_ts`.

    >>> window_clock(0)
    (0, 600)
    >>> window_clock(599)
    (0, 1)
    >>> window_clock(600)
    (1, 600)
    >>> window_clock(1259)
    (2, 541)
    """
    now_ts, window = int(now_ts), int(window)
    return (now_ts // window, window - now_ts % window)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
