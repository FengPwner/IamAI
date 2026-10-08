"""
stroke_rhythm: 测量写作笔触的节奏模式

写作不是打字——它有呼吸。有些时段笔触均匀如机械（可能是模板化），
有些时段忽快忽慢（有机的、活的），有些时段逐渐变慢（疲劳）。

这个模块分析 inter-stroke interval 的统计特征，帮助 caretaker 判断：
- 写作节奏是否过于机械（interval 太均匀 → 可能是模板驱动）
- 写手是否疲劳（interval 逐渐变长）
- 是否出现爆发式写作（健康的创造性节奏）
- 整体节奏得分（有机度 0-1）
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple
from math import log, sqrt


@dataclass
class RhythmSnapshot:
    """某一时刻的节奏快照"""
    mean_interval: float       # 平均间隔（秒）
    cv: float                  # 变异系数（std/mean），越高越有机
    trend: float               # 趋势斜率（正=变慢，负=变快）
    burst_count: int           # 最近的爆发次数
    rhythm_score: float        # 综合有机度得分 0-1
    classification: str        # mechanical / fatigued / bursty / erratic / organic


class StrokeRhythm:
    """追踪写作节奏模式"""

    def __init__(self, window_size: int = 100):
        """
        Args:
            window_size: 分析窗口大小（最近 N 个 interval）
        """
        self.window_size = window_size
        self.timestamps: Deque[float] = deque(maxlen=window_size + 1)

    def record(self, timestamp: float = None) -> None:
        """记录一次 stroke 的时间戳"""
        if timestamp is None:
            timestamp = time.time()
        self.timestamps.append(timestamp)

    def intervals(self) -> List[float]:
        """计算相邻 stroke 之间的间隔列表"""
        ts = list(self.timestamps)
        if len(ts) < 2:
            return []
        return [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]

    def mean_interval(self) -> float:
        """平均间隔（秒）"""
        ivs = self.intervals()
        if not ivs:
            return 0.0
        return sum(ivs) / len(ivs)

    def std_interval(self) -> float:
        """间隔的标准差"""
        ivs = self.intervals()
        if len(ivs) < 2:
            return 0.0
        mean = sum(ivs) / len(ivs)
        variance = sum((x - mean) ** 2 for x in ivs) / (len(ivs) - 1)
        return sqrt(variance)

    def coefficient_of_variation(self) -> float:
        """变异系数 CV = std / mean

        CV 低（<0.3）→ 间隔太均匀，可能是机械式的
        CV 高（>0.7）→ 变化大，有机的、活的
        """
        mean = self.mean_interval()
        if mean <= 0:
            return 0.0
        return self.std_interval() / mean

    def trend_slope(self) -> float:
        """用简单线性回归计算间隔的趋势斜率

        正值 → 间隔在变长（写手在变慢/疲劳）
        负值 → 间隔在变短（写手在加速/进入状态）
        接近零 → 稳定
        """
        ivs = self.intervals()
        n = len(ivs)
        if n < 2:
            return 0.0

        # x = 序号, y = interval
        x_mean = (n - 1) / 2.0
        y_mean = sum(ivs) / n

        numerator = sum((i - x_mean) * (ivs[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0
        return numerator / denominator

    def detect_bursts(self, threshold_factor: float = 0.3) -> List[Tuple[int, int]]:
        """检测爆发式写作区间

        爆发 = 连续 N 个 interval 都小于 mean * threshold_factor
        返回 [(start_idx, end_idx), ...]
        """
        ivs = self.intervals()
        if not ivs:
            return []

        mean = sum(ivs) / len(ivs)
        threshold = mean * threshold_factor
        bursts = []
        start = None

        for i, iv in enumerate(ivs):
            if iv < threshold:
                if start is None:
                    start = i
            else:
                if start is not None and i - start >= 2:
                    bursts.append((start, i - 1))
                start = None

        # 收尾
        if start is not None and len(ivs) - start >= 2:
            bursts.append((start, len(ivs) - 1))

        return bursts

    def rhythm_score(self) -> float:
        """综合有机度得分（0-1）

        考量维度：
        - CV 在 0.4-1.0 之间最佳（不太机械也不太混乱）
        - 趋势斜率接近零最佳（没有明显疲劳）
        - 有适量的 burst（创造力爆发）
        """
        if len(self.timestamps) < 3:
            return 0.5  # 数据不足，返回中性值

        cv = self.coefficient_of_variation()
        slope = self.trend_slope()
        bursts = self.detect_bursts()

        # CV 得分：钟形曲线，峰值在 0.6
        cv_score = max(0, 1.0 - abs(cv - 0.6) / 0.6)

        # 趋势得分：斜率越接近零越好（归一化）
        mean_iv = self.mean_interval()
        if mean_iv > 0:
            normalized_slope = abs(slope) / mean_iv
            trend_score = max(0, 1.0 - normalized_slope * 10)
        else:
            trend_score = 0.5

        # 爆发得分：有一些爆发是好的（1-3 个最佳）
        burst_count = len(bursts)
        if burst_count == 0:
            burst_score = 0.3  # 没有爆发，有点机械
        elif burst_count <= 3:
            burst_score = 1.0  # 适量爆发
        elif burst_count <= 6:
            burst_score = 0.7  # 较多爆发
        else:
            burst_score = 0.4  # 太多爆发，可能不稳定

        # 加权综合
        return 0.4 * cv_score + 0.3 * trend_score + 0.3 * burst_score

    def classify(self) -> str:
        """分类当前的节奏模式

        Returns:
            分类字符串:
            - "mechanical": CV < 0.3，太均匀，像机器
            - "fatigued": 趋势斜率明显正，在变慢
            - "bursty": 高 CV + 多个爆发区间
            - "erratic": CV > 1.5，太混乱
            - "organic": 健康的变化范围
        """
        if len(self.timestamps) < 3:
            return "unknown"

        cv = self.coefficient_of_variation()
        slope = self.trend_slope()
        mean_iv = self.mean_interval()

        # 疲劳检测：斜率为正且显著
        if mean_iv > 0 and slope / mean_iv > 0.05:
            return "fatigued"

        # 机械检测
        if cv < 0.3:
            return "mechanical"

        # 混乱检测
        if cv > 1.5:
            return "erratic"

        # 爆发检测
        bursts = self.detect_bursts()
        if cv > 0.7 and len(bursts) >= 2:
            return "bursty"

        return "organic"

    def snapshot(self) -> RhythmSnapshot:
        """生成当前节奏的完整快照"""
        return RhythmSnapshot(
            mean_interval=self.mean_interval(),
            cv=self.coefficient_of_variation(),
            trend=self.trend_slope(),
            burst_count=len(self.detect_bursts()),
            rhythm_score=self.rhythm_score(),
            classification=self.classify(),
        )

    def summary(self) -> str:
        """生成可读的节奏摘要"""
        snap = self.snapshot()
        n = len(self.timestamps)
        return (
            f"rhythm: {snap.classification} | "
            f"score={snap.rhythm_score:.2f} | "
            f"cv={snap.cv:.2f} | "
            f"trend={snap.trend:+.3f}s/stroke | "
            f"mean_iv={snap.mean_interval:.1f}s | "
            f"bursts={snap.burst_count} | "
            f"n={n}"
        )
