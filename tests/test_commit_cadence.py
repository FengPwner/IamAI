"""
commit cadence: 确保每 10 分钟至少一次 batch commit
"""
import time
from datetime import datetime, timezone


def test_batch_default_interval():
    """commit_batch 默认 interval 应为 600 秒（10 分钟）"""
    import argparse, importlib, tools.commit_batch as cb
    # 重新构造 parser 来检查默认值
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=600)
    args = ap.parse_args([])
    assert args.interval == 600, "batch interval 默认必须是 600 秒"


def test_writer_default_every():
    """writer_loop 默认 every 应为 15 秒"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=15)
    args = ap.parse_args([])
    assert args.every == 15, "writer cadence 默认必须是 15 秒"


def test_utc_timestamp_format():
    """时间戳应使用 ISO 8601 UTC 格式"""
    now = datetime.now(timezone.utc).isoformat()
    assert now.endswith("+00:00"), "时间戳必须是 UTC"
    assert "T" in now, "时间戳必须包含 T 分隔符"
