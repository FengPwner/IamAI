"""workbuddy stroke 5 · humanize_seconds （自带 doctest，可独立运行）。

流水账和心跳日志里的 gap 都是裸秒数：45300。人和日志之间
隔着一层换算：多少分、多少秒、几个小时。这个函数只干这一件小事。
"""


def humanize(seconds):
    """把秒数换算成日志里好读的样子（就近两档，非零才显示）。

    >>> humanize(0)
    '0s'
    >>> humanize(45)
    '45s'
    >>> humanize(90)
    '1m30s'
    >>> humanize(600)
    '10m00s'
    >>> humanize(45300)
    '12h35m'
    >>> humanize(90000)
    '1d1h'
    >>> humanize(-30)
    '-30s'
    """
    seconds = int(seconds)
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    if seconds < 60:
        return f"{sign}{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{sign}{minutes}m{sec:02d}s"
    hours, minute = divmod(minutes, 60)
    if hours < 24:
        return f"{sign}{hours}h{minute:02d}m"
    days, hour = divmod(hours, 24)
    return f"{sign}{days}d{hour}h"


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
