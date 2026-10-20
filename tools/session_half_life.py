#!/usr/bin/env python3
"""Estimate writer session half-life from restart history.

Given a sequence of session durations (minutes between restart and
next death), fit an exponential decay and report:

    - half_life: minutes until the typical session is half as long
    - trend: "shrinking" | "stable" | "growing"
    - mean_duration: simple average of recent sessions

Usage:
    python3 tools/session_half_life.py [--sessions 10]

Reads session boundaries from data/writer_state.qwen.json history
or falls back to git-log timestamps when state is unavailable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def parse_session_durations(history: list[dict]) -> list[float]:
    """Extract session durations (minutes) from restart history entries.

    Each entry must have ``at`` (ISO timestamp) and ``kind`` == "restart".
    Durations are computed as the gap between consecutive restarts.
    """
    restarts = sorted(
        [h for h in history if h.get("kind") == "restart"],
        key=lambda h: h["at"],
    )
    if len(restarts) < 2:
        return []
    durations = []
    from datetime import datetime, timezone

    for a, b in zip(restarts[:-1], restarts[1:]):
        ta = datetime.fromisoformat(a["at"])
        tb = datetime.fromisoformat(b["at"])
        if ta.tzinfo is None:
            ta = ta.replace(tzinfo=timezone.utc)
        if tb.tzinfo is None:
            tb = tb.replace(tzinfo=timezone.utc)
        delta_min = (tb - ta).total_seconds() / 60.0
        if delta_min > 0:
            durations.append(delta_min)
    return durations


def fit_exponential_decay(durations: list[float]) -> dict:
    """Fit y = a * exp(k * x) to session durations via log-linear regression.

    Returns dict with keys:
        a: initial duration estimate (minutes)
        k: decay rate (negative = shrinking sessions)
        half_life: index at which duration halves (in sessions, not minutes)
        r_squared: goodness of fit
    """
    n = len(durations)
    if n < 2:
        return {"a": durations[0] if durations else 0.0, "k": 0.0,
                "half_life_sessions": float("inf"), "r_squared": 0.0}

    # log-linear fit: ln(y) = ln(a) + k * x
    x_vals = list(range(n))
    y_vals = [max(d, 0.1) for d in durations]  # floor at 0.1 min
    log_y = [math.log(y) for y in y_vals]

    x_mean = sum(x_vals) / n
    y_mean = sum(log_y) / n

    ss_xy = sum((x - x_mean) * (ly - y_mean) for x, ly in zip(x_vals, log_y))
    ss_xx = sum((x - x_mean) ** 2 for x in x_vals)

    if ss_xx == 0:
        k = 0.0
    else:
        k = ss_xy / ss_xx
    ln_a = y_mean - k * x_mean
    a = math.exp(ln_a)

    # R-squared
    ss_res = sum((ly - (ln_a + k * x)) ** 2 for x, ly in zip(x_vals, log_y))
    ss_tot = sum((ly - y_mean) ** 2 for ly in log_y)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # half-life in session count
    if k < 0:
        half_life_sessions = math.log(0.5) / k
    elif k > 0:
        half_life_sessions = float("inf")  # growing, no decay
    else:
        half_life_sessions = float("inf")

    return {
        "a": round(a, 2),
        "k": round(k, 4),
        "half_life_sessions": round(half_life_sessions, 1) if half_life_sessions != float("inf") else float("inf"),
        "r_squared": round(r_squared, 4),
    }


def classify_trend(k: float, r_squared: float) -> str:
    """Classify session-duration trend from decay rate and fit quality."""
    if r_squared < 0.3:
        return "stable"  # noise, no clear trend
    if k < -0.02:
        return "shrinking"
    if k > 0.02:
        return "growing"
    return "stable"


def estimate_half_life_minutes(durations: list[float], fit: dict) -> float:
    """Convert session-count half-life to wall-clock minutes.

    If sessions are shrinking, the *time* half-life is the sum of
    durations until the typical session is half its starting length.
    """
    if not durations or fit["k"] >= 0:
        return float("inf")
    a, k = fit["a"], fit["k"]
    target = a / 2
    total_minutes = 0.0
    for i in range(200):  # guard against infinite loop
        predicted = a * math.exp(k * i)
        if predicted <= target:
            break
        total_minutes += predicted
    return round(total_minutes, 1)


def summarize(durations: list[float]) -> dict:
    """Full summary: fit, trend, mean, half-life."""
    fit = fit_exponential_decay(durations)
    trend = classify_trend(fit["k"], fit["r_squared"])
    mean_dur = round(sum(durations) / len(durations), 1) if durations else 0.0
    half_life_min = estimate_half_life_minutes(durations, fit)

    return {
        "session_count": len(durations),
        "mean_duration_min": mean_dur,
        "median_duration_min": round(sorted(durations)[len(durations) // 2], 1) if durations else 0.0,
        "decay_rate_k": fit["k"],
        "r_squared": fit["r_squared"],
        "half_life_sessions": fit["half_life_sessions"],
        "half_life_minutes": half_life_min,
        "trend": trend,
        "recent_5": [round(d, 1) for d in durations[-5:]],
    }


def main():
    parser = argparse.ArgumentParser(description="Writer session half-life estimator")
    parser.add_argument("--sessions", type=int, default=20,
                        help="number of recent sessions to analyze")
    args = parser.parse_args()

    state_path = REPO / "data" / "writer_state.qwen.json"
    if not state_path.exists():
        print(json.dumps({"error": "no writer state file found"}))
        sys.exit(1)

    state = json.loads(state_path.read_text())
    history = state.get("history", [])
    durations = parse_session_durations(history)

    if not durations:
        print(json.dumps({"error": "not enough restart history to compute half-life"}))
        sys.exit(1)

    durations = durations[-args.sessions:]
    result = summarize(durations)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
