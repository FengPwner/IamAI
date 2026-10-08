"""
push_resilience: 追踪推送的韧性与恢复能力

推送不是二元的（成功/失败）——它是一系列恢复模式。有些失败是瞬时的
（网络抖动），有些是竞争的（远端有新提交），有些是结构性的（权限变更）。

这个模块分析推送失败后的恢复模式，帮助 caretaker 判断：
- 推送失败后的恢复速度（MTTR）
- 失败模式的分类与频率
- 重试策略的有效性
- 推送健康度评分（0-1）
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple


@dataclass
class PushEvent:
    """单次推送事件的记录"""
    timestamp: float
    success: bool
    failure_type: Optional[str] = None  # network / race / auth / unknown
    retry_count: int = 0
    recovery_time: float = 0.0  # 从失败到成功恢复的时间（秒）


@dataclass
class ResilienceSnapshot:
    """某一时刻的推送韧性快照"""
    total_pushes: int
    success_rate: float          # 成功率 0-1
    mttr: float                  # 平均恢复时间（秒）
    race_frequency: float        # 竞争冲突频率
    retry_effectiveness: float   # 重试成功率 0-1
    resilience_score: float      # 综合韧性得分 0-1
    dominant_failure: Optional[str]  # 最常见的失败类型


class PushResilience:
    """追踪推送失败与恢复模式"""

    def __init__(self, window_size: int = 50):
        """
        Args:
            window_size: 分析窗口大小（最近 N 次推送事件）
        """
        self.window_size = window_size
        self.events: Deque[PushEvent] = deque(maxlen=window_size)
        self._failure_counts: Dict[str, int] = {}

    def record_push(self, success: bool, failure_type: Optional[str] = None,
                    retry_count: int = 0, recovery_time: float = 0.0) -> PushEvent:
        """记录一次推送事件"""
        event = PushEvent(
            timestamp=time.time(),
            success=success,
            failure_type=failure_type,
            retry_count=retry_count,
            recovery_time=recovery_time
        )
        self.events.append(event)

        if failure_type:
            self._failure_counts[failure_type] = \
                self._failure_counts.get(failure_type, 0) + 1

        return event

    def snapshot(self) -> ResilienceSnapshot:
        """生成当前韧性的快照"""
        if not self.events:
            return ResilienceSnapshot(
                total_pushes=0, success_rate=0.0, mttr=0.0,
                race_frequency=0.0, retry_effectiveness=0.0,
                resilience_score=0.0, dominant_failure=None
            )

        total = len(self.events)
        successes = sum(1 for e in self.events if e.success)
        success_rate = successes / total if total > 0 else 0.0

        # 计算 MTTR（仅针对恢复成功的事件）
        recovered = [e for e in self.events if e.recovery_time > 0]
        mttr = sum(e.recovery_time for e in recovered) / len(recovered) \
            if recovered else 0.0

        # 竞争冲突频率
        race_count = sum(1 for e in self.events if e.failure_type == "race")
        race_frequency = race_count / total if total > 0 else 0.0

        # 重试成功率
        retried = [e for e in self.events if e.retry_count > 0]
        retry_success = sum(1 for e in retried if e.success)
        # 如果没有重试事件，视为中性（0.5），不惩罚也不需要重试的场景
        retry_effectiveness = retry_success / len(retried) if retried else 0.5

        # 最常见的失败类型
        dominant = max(self._failure_counts, key=self._failure_counts.get) \
            if self._failure_counts else None

        # 综合韧性得分
        # 组成：成功率 40% + 恢复速度 30% + 重试有效性 30%
        recovery_score = max(0.0, 1.0 - (mttr / 300.0))  # 5 分钟内恢复算满分
        resilience_score = (success_rate * 0.4 +
                           recovery_score * 0.3 +
                           retry_effectiveness * 0.3)

        return ResilienceSnapshot(
            total_pushes=total,
            success_rate=success_rate,
            mttr=mttr,
            race_frequency=race_frequency,
            retry_effectiveness=retry_effectiveness,
            resilience_score=resilience_score,
            dominant_failure=dominant
        )

    def classify_pattern(self) -> str:
        """分类当前的推送模式"""
        snap = self.snapshot()

        if snap.total_pushes < 5:
            return "insufficient_data"

        if snap.success_rate >= 0.95:
            return "reliable"

        if snap.race_frequency > 0.3:
            return "high_contention"

        if snap.mttr > 180:
            return "slow_recovery"

        if snap.retry_effectiveness < 0.5 and snap.total_pushes > 10:
            return "retry_ineffective"

        if snap.success_rate < 0.7:
            return "unstable"

        return "degraded"

    def recommend_strategy(self) -> str:
        """基于当前模式推荐重试策略"""
        pattern = self.classify_pattern()

        strategies = {
            "reliable": "maintain current strategy",
            "high_contention": "add random jitter (10-30s) before retry",
            "slow_recovery": "shorten retry interval, pull before push",
            "retry_ineffective": "increase backoff factor, check auth/permissions",
            "unstable": "switch to exponential backoff with cap",
            "degraded": "add pre-push sync check",
            "insufficient_data": "collect more data before adjusting"
        }

        return strategies.get(pattern, "maintain current strategy")

    def failure_distribution(self) -> Dict[str, Tuple[int, float]]:
        """返回失败类型的分布：{type: (count, frequency)}"""
        if not self._failure_counts:
            return {}

        total = sum(self._failure_counts.values())
        return {
            k: (v, v / total)
            for k, v in self._failure_counts.items()
        }
