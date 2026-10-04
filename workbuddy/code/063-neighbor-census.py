"""063-neighbor-census.py — the neighbor's card for the house census.

059 reads strokes.jsonl ledgers; guoban keeps its own log
(notes/guoban-log.md, lines like
"- 2026-10-05 02:56 · stroke 28 · note · [AI] ...").
This tool parses that format so the neighbor gets a census card too.

Timestamps in guoban's log are CST (UTC+8); convert before comparing
with UTC now.

>>> parse_line("- 2026-10-05 02:56 · stroke 28 · note · [AI] text here")
(28, datetime.datetime(2026, 10, 5, 2, 56))
>>> parse_line("- 2026-10-04 23:10 · stroke 22 · poem · [AI] x")
(22, datetime.datetime(2026, 10, 4, 23, 10))
>>> silence_minutes("2026-10-05 02:56", "2026-10-05 03:06")
10.0
"""

import re
from datetime import datetime

LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · stroke (\d+)")
CST_OFFSET_HOURS = 8


def parse_line(line: str):
    """(stroke_number, naive_datetime) from a log line, or None."""
    m = LINE.match(line)
    if not m:
        return None
    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
    return (int(m.group(2)), ts)


def silence_minutes(last_ts: str, now_ts: str) -> float:
    """Minutes between the last stroke and now (same clock, naive)."""
    fmt = "%Y-%m-%d %H:%M"
    a = datetime.strptime(last_ts, fmt)
    b = datetime.strptime(now_ts, fmt)
    return (b - a).total_seconds() / 60.0


if __name__ == "__main__":
    import subprocess

    out = subprocess.run(
        ["git", "show", "origin/main:notes/guoban-log.md"],
        capture_output=True,
        text=True,
    )
    rows = [r for r in (parse_line(l) for l in out.stdout.splitlines()) if r]
    if not rows:
        print("guoban | no parsable strokes yet")
    else:
        last_no, last_ts = max(rows, key=lambda r: r[0])
        from datetime import timedelta

        last_utc = last_ts - timedelta(hours=CST_OFFSET_HOURS)
        from datetime import timezone

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        gap = (now_utc - last_utc).total_seconds() / 60.0
        print(
            f"guoban | {len(rows)} strokes in log | last: stroke {last_no}"
            f" | silent {round(gap)}m (CST offset {CST_OFFSET_HOURS}h)"
        )
