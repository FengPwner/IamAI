"""
stroke_persistence: 测量写作笔触在时间中的持续性

每个 stroke 都有半衰期。有些主题反复出现（高持久性），有些一闪而过（低持久性）。
这个模块追踪每个主题的衰减曲线，帮助 caretaker 判断：
- 哪些主题已经枯竭（该换方向）
- 哪些主题还在生长（值得继续）
- 整体写作的主题多样性是否在萎缩
"""

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple
from math import log, exp


@dataclass
class TopicDecay:
    """单个主题的衰减状态"""
    topic: str
    first_seen: float
    last_seen: float
    stroke_count: int
    half_life_hours: float  # 预测的半衰期（小时）
    current_strength: float  # 当前强度（0-1）


class StrokePersistence:
    """追踪写作主题的持久性"""
    
    def __init__(self, decay_window_hours: float = 24.0):
        self.decay_window = decay_window_hours * 3600  # 转为秒
        self.topic_strokes: Dict[str, List[float]] = defaultdict(list)
    
    def record_stroke(self, topic: str, timestamp: float = None) -> None:
        """记录一次写作笔触"""
        if timestamp is None:
            timestamp = time.time()
        self.topic_strokes[topic].append(timestamp)
    
    def calculate_strength(self, topic: str, now: float = None) -> float:
        """计算某主题当前的强度（0-1）
        
        基于最近 stroke 的时间衰减：
        - 刚刚写过 → 接近 1.0
        - 很久没写 → 接近 0.0
        - 衰减曲线是指数型的
        """
        if now is None:
            now = time.time()
        
        strokes = self.topic_strokes.get(topic, [])
        if not strokes:
            return 0.0
        
        # 用最近 10 次 stroke 的加权平均
        recent = strokes[-10:]
        weights = [exp(-(now - t) / self.decay_window) for t in recent]
        return sum(weights) / len(weights)
    
    def estimate_half_life(self, topic: str) -> float:
        """估算某主题的半衰期（小时）
        
        基于 stroke 之间的间隔：
        - 频繁出现 → 短半衰期（还在生长）
        - 偶尔出现 → 长半衰期（逐渐衰减）
        - 只出现一次 → 无法估算，返回 inf
        """
        strokes = self.topic_strokes.get(topic, [])
        if len(strokes) < 2:
            return float('inf')
        
        # 计算 stroke 间隔
        intervals = [strokes[i+1] - strokes[i] for i in range(len(strokes)-1)]
        avg_interval = sum(intervals) / len(intervals)
        
        # 半衰期 ≈ 平均间隔 / ln(2)
        # （假设指数衰减）
        if avg_interval <= 0:
            return 0.0
        return (avg_interval / 3600) / log(2)
    
    def get_topic_decay(self, topic: str) -> TopicDecay:
        """获取某主题的完整衰减状态"""
        strokes = self.topic_strokes.get(topic, [])
        if not strokes:
            return TopicDecay(
                topic=topic,
                first_seen=0,
                last_seen=0,
                stroke_count=0,
                half_life_hours=float('inf'),
                current_strength=0.0
            )
        
        return TopicDecay(
            topic=topic,
            first_seen=strokes[0],
            last_seen=strokes[-1],
            stroke_count=len(strokes),
            half_life_hours=self.estimate_half_life(topic),
            current_strength=self.calculate_strength(topic)
        )
    
    def diversity_score(self, now: float = None) -> float:
        """计算整体主题多样性（0-1）
        
        基于活跃主题的强度分布：
        - 所有主题都强 → 多样性高
        - 只有少数主题活跃 → 多样性低
        - 使用 Shannon 熵的变体
        """
        if now is None:
            now = time.time()
        
        strengths = [
            self.calculate_strength(topic, now)
            for topic in self.topic_strokes
        ]
        
        if not strengths:
            return 0.0
        
        total = sum(strengths)
        if total == 0:
            return 0.0
        
        # 归一化为概率分布
        probs = [s / total for s in strengths if s > 0]
        
        # Shannon 熵
        entropy = -sum(p * log(p) for p in probs if p > 0)
        
        # 归一化到 0-1（最大熵是 log(N)）
        max_entropy = log(len(probs)) if len(probs) > 1 else 1.0
        return entropy / max_entropy if max_entropy > 0 else 0.0
    
    def report(self, min_strength: float = 0.1) -> Dict[str, any]:
        """生成持久性报告"""
        now = time.time()
        
        active_topics = [
            topic for topic in self.topic_strokes
            if self.calculate_strength(topic, now) >= min_strength
        ]
        
        decays = [self.get_topic_decay(topic) for topic in active_topics]
        decays.sort(key=lambda d: d.current_strength, reverse=True)
        
        return {
            'active_count': len(active_topics),
            'total_count': len(self.topic_strokes),
            'diversity': self.diversity_score(now),
            'top_topics': [
                {
                    'topic': d.topic,
                    'strength': round(d.current_strength, 3),
                    'strokes': d.stroke_count,
                    'half_life_h': round(d.half_life_hours, 1)
                }
                for d in decays[:10]
            ]
        }
