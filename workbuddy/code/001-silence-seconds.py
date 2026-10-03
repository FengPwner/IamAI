"""workbuddy stroke 1 · since_last_stroke （自带 doctest，可独立运行）。

写手之间互相不打招呼，唯一的问候是去看对方状态文件里的时间戳。
这个模块把两个时间戳之间的沉默换算成数字，并沿用 roster.py 的存活判定：
沉默不超过两倍"写一笔的间隔"，就算还活着。
"""

from datetime import datetime, timezone


def _parse(moment):
    """ISO 字符串转 datetime； naive 就当 UTC。

    >>> _parse("2026-10-03T10:00:00+00:00").tzinfo is not None
    True
    """
    parsed = datetime.fromisoformat(moment.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def silence_seconds(last_at, now_at):
    """两个时间戳之间隔了多少秒沉默。

    >>> silence_seconds("2026-10-03T10:00:00+00:00", "2026-10-03T10:00:30+00:00")
    30
    >>> silence_seconds("2026-10-03T10:00:00Z", "2026-10-03T10:01:00+00:00")
    60
    """
    return int((_parse(now_at) - _parse(last_at)).total_seconds())


def is_alive(last_at, now_at, every=15):
    """沉默不超过两倍写一笔的间隔，就算还活着。

    >>> is_alive("2026-10-03T10:00:00+00:00", "2026-10-03T10:00:29+00:00", every=15)
    True
    >>> is_alive("2026-10-03T10:00:00+00:00", "2026-10-03T10:00:31+00:00", every=15)
    False
    """
    return silence_seconds(last_at, now_at) <= 2 * int(every)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
