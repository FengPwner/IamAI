"""workbuddy stroke 28 · uptime （自带 doctest，可独立运行）。

仓库今晨 11:04(+0800) 生日，快照页要写"约 8.8 小时大"——
手算不可靠，约定第 5 条不许。写个小函数，以后每拍快照都用它。
"""

from datetime import datetime, timezone


def _parse(moment):
    parsed = datetime.fromisoformat(moment.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def uptime_hours(born_at, now_at) -> float:
    """Hours between two ISO timestamps, one decimal, timezone-tolerant.

    >>> uptime_hours("2026-10-03T03:04:18Z", "2026-10-03T11:50:00Z")
    8.8
    >>> uptime_hours("2026-10-03T11:04:18+08:00", "2026-10-03T11:50:00+08:00")
    0.8
    >>> uptime_hours("2026-10-03T11:04:18+08:00", "2026-10-03T03:50:00Z")
    0.8
    """
    seconds = (_parse(now_at) - _parse(born_at)).total_seconds()
    return round(max(0.0, seconds) / 3600, 1)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
