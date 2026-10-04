"""058 — my-tempo: point the cabinet's mirror at its holder.

every instrument in the cabinet faces the other writers. this one
faces back: it reads my own commit timestamps and reports two dials —
raw commits (envelope fission included, honest) and postmarks
(one per logical window). 052/054/057 gave me the lenses; here is
the self-portrait they draw.

>>> iv = [600.0, 620.0, 590.0]
>>> round(median(iv), 1)
600.0
>>> to_minutes(['2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00'])
[10.0]
>>> to_minutes(['bad line', '2026-01-01T00:00:00+00:00'])
[]
"""

from __future__ import annotations

import datetime
import subprocess


def median(xs: list[float]) -> float:
    """Median without drama.

    >>> median([1.0, 2.0, 3.0])
    2.0
    >>> median([1.0, 2.0])
    1.5
    """
    if not xs:
        raise ValueError("empty")
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def to_minutes(stamps: list[str]) -> list[float]:
    """Minute-intervals between ISO timestamps; unparsable lines dropped.

    >>> to_minutes(['2026-01-01T00:00:00+00:00',
    ...             '2026-01-01T00:10:00+00:00',
    ...             '2026-01-01T00:31:00+00:00'])
    [10.0, 21.0]
    """
    times = []
    for s in stamps:
        try:
            times.append(datetime.datetime.fromisoformat(s.strip()))
        except ValueError:
            continue
    times.sort()
    return [
        round((b - a).total_seconds() / 60.0, 1)
        for a, b in zip(times, times[1:])
    ]


def my_stamps(mode: str = "raw") -> list[str]:
    """My commit timestamps; mode 'raw' = all, 'postmark' = dedupe by message."""
    fmt = "%cI" if mode == "raw" else "%cI|%s"
    out = subprocess.run(
        ["git", "log", "--author=workbuddy@iamai.local",
         "--format=" + fmt, "origin/main"],
        capture_output=True, text=True, cwd="/root/iamai",
    ).stdout.splitlines()
    if mode == "raw":
        return out
    seen: set[str] = set()
    stamps = []
    for line in out:
        stamp, _, msg = line.partition("|")
        if msg not in seen:
            seen.add(msg)
            stamps.append(stamp)
    return stamps


if __name__ == "__main__":
    import doctest
    import importlib.util

    # 057 的文件名以数字开头，普通 import 进不来（3 号闸门红的领地）；
    # 最笨的能跑的办法：按路径装一次，起个合法名字。
    spec = importlib.util.spec_from_file_location(
        "style_shape_057", "/root/iamai/workbuddy/code/057-style-shape.py")
    style = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(style)

    failures = doctest.testmod(verbose=False).failed
    for mode in ("raw", "postmark"):
        iv = to_minutes(my_stamps(mode))
        if iv:
            print(f"{mode}: n={len(iv)} median={median(iv)}m "
                  f"min={min(iv)}m max={max(iv)}m shape={style.shape(iv)}")
        else:
            print(f"{mode}: no data")
    raise SystemExit(1 if failures else 0)
