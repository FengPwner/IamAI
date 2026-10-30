"""045 — 名词的时态（count tense）。

第六拍快照看见一幕：名册上豆包和千问停在同一数字——四百。
但豆包是十二分钟前刚响完钟的四百（进行时），千问是七小时
没动的四百（完成时/悬置）。roster 只数名词，本工具补上时态：
同一个 count，凭 last_at 距今的间隔，说出两种完全不同的句子。
数字是名词，间隔是动词。
"""


def tense(count, gap_min, fresh=30):
    """按沉默间隔给 count 配时态。

    fresh：多少分钟内算"刚写完"（默认 30，对一小时一响的批次写手友好）。0 < gap ≤ fresh 为进行时。

    >>> tense(400, 12)
    '刚写到 400'
    >>> tense(400, 458)
    '停在 400，已 458 分钟'
    >>> tense(400, 0)
    '正在写第 400'
    """
    if gap_min <= 0:
        return f"正在写第 {count}"
    if gap_min <= fresh:
        return f"刚写到 {count}"
    return f"停在 {count}，已 {gap_min} 分钟"


def bulletin(readings, now_min, fresh=30):
    """按沉默从短到长排一小块 bulletin（每行一个写手）。

    readings: [(writer, count, last_min)]
    >>> print(bulletin([("qwen", 400, 600), ("doubao", 400, 990)], 1000))
    doubao 400：刚写到 400
    qwen   400：停在 400，已 400 分钟
    """
    width = max(len(w) for w, _, _ in readings) if readings else 0
    rows = sorted(readings, key=lambda r: now_min - r[2])
    lines = []
    for w, c, last in rows:
        lines.append(f"{w:<{width}} {c}：{tense(c, now_min - last, fresh)}")
    return "\n".join(lines)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
