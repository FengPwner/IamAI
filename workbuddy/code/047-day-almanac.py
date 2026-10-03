"""047 — 一日编年（day almanac）。

给"今天"一个可携带的摘要：从 `git log --format='%ad|%an'` 的输出里
抽出某一天的首末提交、跨度、每小时的写手出场。
全天最忙的一小时是高峰，最空的一小时多半是网络在打盹。
编年不解释原因，只把"什么时候、谁、多少"钉在一页纸上。
"""

from collections import Counter, defaultdict


def parse(lines):
    """解析 'MM-DD HH:MM|author' 行，按日期分组为 {day: [(hh, author)]}。

    >>> parse(["10-03 10:05|workbuddy", "10-03 10:16|Qwen", "10-04 03:23|Doubao"])
    {'10-03': [(10, 'workbuddy'), (10, 'Qwen')], '10-04': [(3, 'Doubao')]}
    """
    days = defaultdict(list)
    for ln in lines:
        ln = ln.strip()
        if "|" not in ln or " " not in ln.split("|")[0]:
            continue
        stamp, author = ln.split("|", 1)
        day, hm = stamp.split()
        days[day].append((int(hm.split(":")[0]), author))
    return dict(days)


def almanac(entries):
    """一天的编年：首末时刻、跨度、最忙小时。

    entries: [(hour, author)]（按出现顺序）
    >>> almanac([(10, 'a'), (10, 'b'), (11, 'a'), (14, 'c')])
    {'first': 10, 'last': 14, 'span_h': 4, 'busiest': (10, 2)}
    """
    hours = [h for h, _ in entries]
    counts = Counter(hours)
    busiest = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "first": min(hours),
        "last": max(hours),
        "span_h": max(hours) - min(hours),
        "busiest": busiest,
    }


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
