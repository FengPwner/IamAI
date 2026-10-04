"""061-window-ledger.py — measured window durations: the ceiling ledger.

Division of labor: 055 models the floor (budget); this tool records what
actually happened. A window row is (name, launch_utc, land_utc, attempts),
timestamps HH:MM:SS from the task logs — measured numbers only.

The night's weather, windows 211-214 (2026-10-04): storm, then calm.

>>> rows = [("211", "16:54:00", "17:07:49", 4),
...         ("212", "17:18:00", "17:26:23", 5),
...         ("213", "17:36:30", "17:38:36", 2),
...         ("214", "17:48:36", "17:51:02", 1)]
>>> durations(rows)
[829.0, 503.0, 126.0, 146.0]
>>> max(rows, key=lambda r: duration(r[1], r[2]))[0]
'211'
>>> len([v for v in verdicts(rows) if v[2] == "breached band"])
0
"""

from datetime import datetime


def duration(launch: str, land: str) -> float:
    """Seconds between two HH:MM:SS timestamps of the same night.

    >>> duration("16:54:00", "17:07:49")
    829.0
    >>> duration("17:48:36", "17:51:02")
    146.0
    """
    fmt = "%H:%M:%S"
    a = datetime.strptime(launch, fmt)
    b = datetime.strptime(land, fmt)
    return (b - a).total_seconds()


def durations(rows) -> list:
    """Durations in row order."""
    return [duration(r[1], r[2]) for r in rows]


def verdicts(rows, band: float = 900.0) -> list:
    """Per-window (name, seconds, verdict) against the 1.5x band."""
    out = []
    for name, launch, land, _attempts in rows:
        d = duration(launch, land)
        out.append((name, d, "within band" if d <= band else "breached band"))
    return out


if __name__ == "__main__":
    rows = [
        ("211", "16:54:00", "17:07:49", 4),
        ("212", "17:18:00", "17:26:23", 5),
        ("213", "17:36:30", "17:38:36", 2),
        ("214", "17:48:36", "17:51:02", 1),
        ("230", "20:42:10", "20:45:24", 1),
        ("231", "20:59:35", "21:01:13", 2),
        ("232", "21:12:00", "21:13:24", 1),
        ("233", "21:23:00", "21:29:33", 4),
        ("234", "21:40:00", "21:40:16", 1),
    ]
    ds = durations(rows)
    print("durations:", [round(d) for d in ds], "s")
    print("max:", max(ds), "s | min:", min(ds), "s")
    print("median:", sorted(ds)[len(ds) // 2 - 1 : len(ds) // 2 + 1])
    for name, d, v in verdicts(rows):
        print(f"window {name}: {round(d)}s -> {v}")
    print("(window 175, ~21 min, predates the precise ledger; see log)")
