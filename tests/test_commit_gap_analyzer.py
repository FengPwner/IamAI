"""tests for scripts/commit_gap_analyzer.py"""

import sys
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# 将 scripts/ 加入 import 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from commit_gap_analyzer import (
    compute_gaps,
    analyze,
    format_report,
    get_commit_timestamps,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_entries(offsets_minutes: list[int], base: datetime | None = None) -> list[dict]:
    """
    构造 mock 提交条目列表。
    offsets_minutes: 每条提交相对于 base 的偏移（分钟）。
    """
    if base is None:
        base = datetime(2026, 10, 21, 10, 0, 0, tzinfo=timezone.utc)
    return [
        {"timestamp": base + timedelta(minutes=m), "message": f"commit-{i}"}
        for i, m in enumerate(offsets_minutes)
    ]


# ── compute_gaps ─────────────────────────────────────────────────────

class TestComputeGaps:
    def test_empty_input(self):
        assert compute_gaps([]) == []

    def test_single_entry(self):
        entries = _make_entries([0])
        assert compute_gaps(entries) == []

    def test_two_entries(self):
        entries = _make_entries([0, 10])
        gaps = compute_gaps(entries)
        assert len(gaps) == 1
        assert gaps[0]["gap_seconds"] == 600.0
        assert gaps[0]["from_commit"] == "commit-0"
        assert gaps[0]["to_commit"] == "commit-1"

    def test_multiple_entries(self):
        entries = _make_entries([0, 5, 15, 20])
        gaps = compute_gaps(entries)
        assert len(gaps) == 3
        assert gaps[0]["gap_seconds"] == 300.0   # 5 min
        assert gaps[1]["gap_seconds"] == 600.0   # 10 min
        assert gaps[2]["gap_seconds"] == 300.0   # 5 min

    def test_gap_at_field_is_isoformat(self):
        entries = _make_entries([0, 10])
        gaps = compute_gaps(entries)
        # 应该能被 datetime.fromisoformat 解析
        ts = datetime.fromisoformat(gaps[0]["at"])
        assert ts.year == 2026


# ── analyze ──────────────────────────────────────────────────────────

class TestAnalyze:
    def test_empty_gaps(self):
        stats = analyze([])
        assert stats["total_commits"] == 0
        assert stats["avg_gap_s"] == 0
        assert stats["rhythm_stability"] == 0.0

    def test_single_gap(self):
        gaps = [{"gap_seconds": 600, "from_commit": "a", "to_commit": "b",
                 "at": "2026-10-21T10:10:00+00:00"}]
        stats = analyze(gaps)
        assert stats["total_commits"] == 2
        assert stats["avg_gap_s"] == 600.0
        assert stats["max_gap_s"] == 600.0
        assert stats["stall_count"] == 0
        # 单个间隔 → 稳定性 1.0
        assert stats["rhythm_stability"] == 1.0

    def test_uniform_gaps_high_stability(self):
        """完全均匀的间隔 → 稳定性接近 1.0"""
        gaps = [
            {"gap_seconds": 600, "from_commit": f"c{i}", "to_commit": f"c{i+1}",
             "at": f"2026-10-21T10:{10+i*10:02d}:00+00:00"}
            for i in range(10)
        ]
        stats = analyze(gaps)
        assert stats["rhythm_stability"] > 0.99

    def test_variable_gaps_lower_stability(self):
        """间隔差异大 → 稳定性明显低于 1.0"""
        values = [100, 2000, 50, 3000, 200]
        gaps = [
            {"gap_seconds": v, "from_commit": f"c{i}", "to_commit": f"c{i+1}",
             "at": f"2026-10-21T10:{i:02d}:00+00:00"}
            for i, v in enumerate(values)
        ]
        stats = analyze(gaps)
        assert stats["rhythm_stability"] < 0.5

    def test_stall_count_with_threshold(self):
        gaps = [
            {"gap_seconds": 300, "from_commit": "a", "to_commit": "b",
             "at": "2026-10-21T10:05:00+00:00"},
            {"gap_seconds": 1500, "from_commit": "b", "to_commit": "c",
             "at": "2026-10-21T10:30:00+00:00"},
            {"gap_seconds": 600, "from_commit": "c", "to_commit": "d",
             "at": "2026-10-21T10:40:00+00:00"},
            {"gap_seconds": 2000, "from_commit": "d", "to_commit": "e",
             "at": "2026-10-21T11:13:00+00:00"},
        ]
        stats = analyze(gaps, stall_threshold_s=1200)
        assert stats["stall_count"] == 2  # 1500s 和 2000s 超过阈值
        assert stats["max_gap_s"] == 2000.0

    def test_max_gap_identification(self):
        gaps = [
            {"gap_seconds": 100, "from_commit": "a", "to_commit": "b",
             "at": "2026-10-21T10:01:00+00:00"},
            {"gap_seconds": 5000, "from_commit": "b", "to_commit": "c",
             "at": "2026-10-21T11:24:00+00:00"},
            {"gap_seconds": 200, "from_commit": "c", "to_commit": "d",
             "at": "2026-10-21T11:28:00+00:00"},
        ]
        stats = analyze(gaps)
        assert stats["max_gap_s"] == 5000.0
        assert stats["max_gap_from"] == "b"
        assert stats["max_gap_to"] == "c"


# ── format_report ────────────────────────────────────────────────────

class TestFormatReport:
    def test_empty_stats(self):
        report = format_report({"total_commits": 0, "avg_gap_s": 0, "max_gap_s": 0,
                                "max_gap_at": None, "stall_count": 0,
                                "rhythm_stability": 0.0, "stall_threshold_s": 1200})
        assert "无提交数据" in report

    def test_normal_report_contains_key_fields(self):
        stats = {
            "total_commits": 10,
            "avg_gap_s": 600.0,
            "max_gap_s": 1800.0,
            "max_gap_at": "2026-10-21T10:30:00+00:00",
            "max_gap_from": "add feature X",
            "max_gap_to": "fix typo in Y",
            "stall_count": 1,
            "stall_threshold_s": 1200.0,
            "rhythm_stability": 0.75,
        }
        report = format_report(stats)
        assert "提交总数: 10" in report
        assert "平均间隔: 600s" in report
        assert "最大间隔: 1800s" in report
        assert "停摆次数: 1" in report
        assert "0.750" in report


# ── get_commit_timestamps (integration, uses real git) ───────────────

class TestGetCommitTimestamps:
    def test_real_repo(self):
        """用本仓库做集成测试——至少有若干提交。"""
        repo = str(Path(__file__).resolve().parent.parent)
        entries = get_commit_timestamps(repo, last_n=10)
        assert len(entries) >= 2
        assert "timestamp" in entries[0]
        assert "message" in entries[0]

    def test_nonexistent_repo(self):
        entries = get_commit_timestamps("/tmp/nonexistent_repo_xyz_12345")
        assert entries == []

    def test_small_last_n(self):
        repo = str(Path(__file__).resolve().parent.parent)
        entries = get_commit_timestamps(repo, last_n=3)
        assert len(entries) <= 3


# ── end-to-end pipeline ──────────────────────────────────────────────

class TestEndToEnd:
    def test_full_pipeline(self):
        """构造条目 → 计算间隔 → 分析 → 格式化，完整走一遍。"""
        entries = _make_entries([0, 10, 20, 30, 50, 60, 80])
        gaps = compute_gaps(entries)
        stats = analyze(gaps, stall_threshold_s=900)
        report = format_report(stats)

        assert stats["total_commits"] == 7
        # gaps: 600, 600, 600, 1200, 600, 1200 — 30→50 和 60→80 各 1200s > 900s
        assert stats["stall_count"] == 2
        assert "=== 提交节奏分析报告 ===" in report
        assert "停摆次数: 2" in report
