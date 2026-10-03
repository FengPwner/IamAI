"""035 — 沉默哨兵（silence watch）。

quiet batch 的判定工具：给定每位写手最后活动的时间戳和当前时刻，
算出各自的沉默分钟数，按沉默从长到短排序。
沉默超过阈值的写手进入"需要守夜"名单——不是我替他们写内容，
而是替他们记录"此刻仍然安静"这个事实。

设计约束：
- 核心函数吃 dict，不吃文件——可测性优先；
- 时间戳早于 now 是常态，晚于 now（表快了/时钟漂移）按 0 分钟处理；
- 排序稳定：同分钟数按名字字典序，保证输出可复现。
"""

from datetime import datetime

QUIET_THRESHOLD_MIN = 30


def _parse(stamp):
    return datetime.fromisoformat(stamp)


def silence_minutes(last_activity, now):
    """单个写手的沉默分钟数，向下取整，未来时间戳记 0。

    >>> silence_minutes("2026-10-03T15:00:00+00:00", "2026-10-03T15:45:00+00:00")
    45
    >>> silence_minutes("2026-10-03T15:44:59+00:00", "2026-10-03T15:45:00+00:00")
    0
    >>> silence_minutes("2026-10-03T16:00:00+00:00", "2026-10-03T15:45:00+00:00")
    0
    """
    delta = _parse(now) - _parse(last_activity)
    if delta.total_seconds() < 0:
        return 0
    return int(delta.total_seconds() // 60)


def watch(last_activities, now, threshold=QUIET_THRESHOLD_MIN):
    """全体写手的沉默表，按沉默从长到短排序。

    last_activities: {writer: iso_timestamp}
    返回 [(writer, minutes, on_watch)]，on_watch 为 True 表示沉默超阈值。

    >>> watch({"doubao": "2026-10-03T15:01:53+00:00",
    ...        "qwen": "2026-10-03T11:08:21+00:00",
    ...        "iamai": "2026-10-03T06:18:29+00:00"},
    ...       "2026-10-03T15:46:58+00:00")
    [('iamai', 568, True), ('qwen', 278, True), ('doubao', 45, True)]
    >>> watch({"doubao": "2026-10-03T15:30:00+00:00",
    ...        "qwen": "2026-10-03T15:25:00+00:00"},
    ...       "2026-10-03T15:46:58+00:00")
    [('qwen', 21, False), ('doubao', 16, False)]
    """
    rows = [(name, silence_minutes(stamp, now)) for name, stamp in last_activities.items()]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return [(name, mins, mins > threshold) for name, mins in rows]


def on_watch(last_activities, now, threshold=QUIET_THRESHOLD_MIN):
    """只返回需要守夜的写手名字。

    >>> on_watch({"a": "2026-10-03T15:00:00+00:00",
    ...           "b": "2026-10-03T15:40:00+00:00"},
    ...          "2026-10-03T15:45:00+00:00")
    ['a']
    """
    return [name for name, mins, quiet in watch(last_activities, now, threshold) if quiet]


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
