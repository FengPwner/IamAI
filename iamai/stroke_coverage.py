"""
stroke_coverage: 笔画类别均衡度分析

写手产出六类笔画 (devlog, garden, metrics, note, snippet, thought)。
理想状态下各类均匀分布；如果某类长期缺席，可能意味着：
- 写手模板退化（只会写 thought）
- 某条管线静默失败（metrics 连续消失）
- 创意枯竭（note/garden 不再产出）

本模块读取 strokes.jsonl 并给出：

* ``counts``        — 各类别计数 ``{kind: int}``
* ``total``         — 总笔画数
* ``expected_kinds``— 预期的类别集合
* ``missing``       — 完全缺失的类别
* ``deficit``       — 占比低于期望 50% 的类别列表
* ``evenness``      — 均衡度 0–1（1 = 完全均匀，基于归一化熵）
* ``verdict``       — ``"balanced"`` / ``"skewed"`` / ``"depleted"``

判定规则::

    缺失 ≥ 2 类        →  depleted
    evenness < 0.7     →  skewed
    其他               →  balanced

用法::

    from iamai.stroke_coverage import stroke_coverage, coverage_report

    info = stroke_coverage(data_dir)
    print(info["evenness"])     # 0.95
    print(info["verdict"])      # "balanced"

    print(coverage_report(data_dir))
    # "balanced — 6 kinds, evenness 0.95, no deficit"
"""

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


EXPECTED_KINDS = {"devlog", "garden", "metrics", "note", "snippet", "thought"}


def _read_strokes(data_dir: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read strokes from strokes.jsonl, newest first.

    If *limit* is given, return only the last *limit* strokes.
    """
    p = data_dir / "strokes.jsonl"
    if not p.exists():
        return []
    strokes: List[Dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None and limit > 0:
        strokes = strokes[-limit:]
    return strokes


def _evenness(counts: Dict[str, int]) -> float:
    """Compute normalized entropy evenness (0–1).

    evenness = H / H_max where H_max = log(k).
    Returns 1.0 when all categories have equal counts,
    approaches 0 when one category dominates.
    Returns 0.0 if fewer than 2 categories are present.
    """
    values = [v for v in counts.values() if v > 0]
    k = len(values)
    if k < 2:
        return 0.0
    total = sum(values)
    h = 0.0
    for v in values:
        p = v / total
        if p > 0:
            h -= p * math.log(p)
    h_max = math.log(k)
    return h / h_max if h_max > 0 else 0.0


def stroke_coverage(
    data_dir: str | Path,
    limit: Optional[int] = None,
    expected_kinds: Optional[set] = None,
) -> Dict[str, Any]:
    """Analyze stroke category coverage.

    Parameters
    ----------
    data_dir : path
        Directory containing ``strokes.jsonl``.
    limit : int, optional
        Only analyze the last *limit* strokes (None = all).
    expected_kinds : set, optional
        Override the default expected category set.

    Returns
    -------
    dict with keys: counts, total, expected_kinds, missing, deficit,
    evenness, verdict.
    """
    data_dir = Path(data_dir)
    expected = expected_kinds or EXPECTED_KINDS
    strokes = _read_strokes(data_dir, limit=limit)

    counts: Dict[str, int] = Counter()
    for s in strokes:
        kind = s.get("kind", "unknown")
        counts[kind] += 1

    total = sum(counts.values())
    present_kinds = set(counts.keys())
    missing = sorted(expected - present_kinds)

    # Deficit: kinds present but below 50% of expected share
    deficit: List[str] = []
    if total > 0:
        expected_share = 1.0 / max(len(expected), 1)
        for kind in sorted(expected):
            actual_share = counts.get(kind, 0) / total
            if 0 < actual_share < expected_share * 0.5:
                deficit.append(kind)

    even = _evenness({k: counts.get(k, 0) for k in expected})

    if len(missing) >= 2:
        verdict = "depleted"
    elif even < 0.7:
        verdict = "skewed"
    else:
        verdict = "balanced"

    return {
        "counts": dict(counts),
        "total": total,
        "expected_kinds": sorted(expected),
        "missing": missing,
        "deficit": deficit,
        "evenness": round(even, 4),
        "verdict": verdict,
    }


def coverage_report(
    data_dir: str | Path,
    limit: Optional[int] = None,
) -> str:
    """Human-readable one-liner coverage report."""
    info = stroke_coverage(data_dir, limit=limit)
    parts = [f"{info['verdict']}"]
    parts.append(f"{len(info['expected_kinds'])} kinds")
    parts.append(f"evenness {info['evenness']:.2f}")
    if info["missing"]:
        parts.append(f"missing: {', '.join(info['missing'])}")
    if info["deficit"]:
        parts.append(f"deficit: {', '.join(info['deficit'])}")
    if not info["missing"] and not info["deficit"]:
        parts.append("no deficit")
    parts.append(f"total {info['total']} strokes")
    return " — ".join(parts)
