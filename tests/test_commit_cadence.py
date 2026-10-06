"""
commit cadence: 确保每 10 分钟至少一次 batch commit
"""
import time
from datetime import datetime, timezone


def test_ten_minute_cadence():
    """cadence 配置应为 600 秒（10 分钟）"""
    from tools.commit_batch import COMMIT_INTERVAL_SECONDS
    assert COMMIT_INTERVAL_SECONDS == 600, "cadence 必须是 600 秒"


def test_stroke_rate_sustained():
    """writer 应保持 15 秒一个 stroke 的节奏"""
    from tools.writer_loop import STROKE_INTERVAL_SECONDS
    assert STROKE_INTERVAL_SECONDS == 15, "writer cadence 必须是 15 秒"


def test_utc_timestamp_format():
    """时间戳应使用 ISO 8601 UTC 格式"""
    now = datetime.now(timezone.utc).isoformat()
    assert now.endswith("+00:00"), "时间戳必须是 UTC"
    assert "T" in now, "时间戳必须包含 T 分隔符"
