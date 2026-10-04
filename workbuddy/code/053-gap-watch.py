"""053 gap-watch: 沉默守望计时。

给最后一次落笔时刻与当前时刻,报告沉默时长,并对照历史最长间隔
判定状态:寻常,还是刷新纪录。钟实验第十二战的副产物——
带管迟到,这个管失踪期间的表盘读数。

>>> gap_minutes('2026-10-04T03:00:00+00:00', '2026-10-04T03:30:00+00:00')
30.0
>>> status(50.0, 72)
'normal'
>>> status(96.0, 72)
'record'
>>> fmt(96.5)
'96m30s'
"""

from datetime import datetime


def _parse(iso):
    return datetime.datetime.fromisoformat(iso)


def gap_minutes(last_iso, now_iso):
    """两个 ISO 时刻之间的分钟数(浮点)。"""
    return (_parse(now_iso) - _parse(last_iso)).total_seconds() / 60.0


def status(gap, max_known):
    """gap 超过历史最长间隔 = 刷新纪录;否则寻常。"""
    return 'record' if gap > max_known else 'normal'


def fmt(minutes):
    """分钟数 → 'Xm Ys' 人话(秒取整)。"""
    total = round(minutes * 60)
    return "%dm%02ds" % (total // 60, total % 60)


if __name__ == "__main__":
    import doctest
    import json
    import datetime
    assert doctest.testmod().failed == 0
    d = json.load(open('data/writer_state.doubao.json'))
    last = d['history'][-1]['at']
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    gap = gap_minutes(last, now)
    print("doubao last:", last)
    print("silence:", fmt(gap), "— status:", status(gap, 72.0))
