"""guoban stroke 9 · window_index （自带 doctest，可独立运行）。"""

import hashlib  # noqa: F401  (stable_pick 用)


def window_index(now_ts, window=600):
    """把时间戳切进固定大小的窗口。

    >>> window_index(0, 600)
    0
    >>> window_index(599, 600)
    0
    >>> window_index(600, 600)
    1
    >>> window_index(1259, 600)
    2
    """
    return int(now_ts) // int(window)
