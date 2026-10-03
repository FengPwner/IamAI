"""workbuddy stroke 6 · covered_windows （自带 doctest，可独立运行）。

十分钟一格是这个仓库的时间刻度。给一段起止时间，
问"它横跨了哪几个窗口"——补日志、对账、找空窗都用得上。
"""


def covered_windows(start_ts, end_ts, window=600):
    """闭区间 [start_ts, end_ts] 触及的所有窗口编号，升序。

    >>> covered_windows(0, 599)
    [0]
    >>> covered_windows(0, 600)
    [0, 1]
    >>> covered_windows(1259, 1259)
    [2]
    >>> covered_windows(599, 601)
    [0, 1]
    """
    start_ts, end_ts = int(start_ts), int(end_ts)
    if end_ts < start_ts:
        raise ValueError("end before start")
    window = int(window)
    first, last = start_ts // window, end_ts // window
    return list(range(first, last + 1))


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
