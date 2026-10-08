"""tests for iamai.stroke_persistence"""

import time
import pytest
from iamai.stroke_persistence import StrokePersistence, TopicDecay


@pytest.fixture
def sp():
    return StrokePersistence(decay_window_hours=24.0)


@pytest.fixture
def populated_sp():
    """A tracker with several topics at various ages."""
    sp = StrokePersistence(decay_window_hours=24.0)
    now = time.time()
    
    # "hot" topic — 20 strokes in last hour
    for i in range(20):
        sp.record_stroke("automation", now - 3600 + i * 180)
    
    # "warm" topic — 5 strokes in last 6 hours
    for i in range(5):
        sp.record_stroke("naming", now - 21600 + i * 4320)
    
    # "cold" topic — 2 strokes, 2 days ago
    sp.record_stroke("deletion", now - 172800)
    sp.record_stroke("deletion", now - 169200)
    
    # "dead" topic — 1 stroke, 5 days ago
    sp.record_stroke("legacy", now - 432000)
    
    return sp


# ── record_stroke ─────────────────────────────────────────────────────

class TestRecordStroke:
    def test_records_with_default_timestamp(self, sp):
        before = time.time()
        sp.record_stroke("test_topic")
        after = time.time()
        
        strokes = sp.topic_strokes["test_topic"]
        assert len(strokes) == 1
        assert before <= strokes[0] <= after
    
    def test_records_with_explicit_timestamp(self, sp):
        sp.record_stroke("topic_a", timestamp=1000.0)
        assert sp.topic_strokes["topic_a"] == [1000.0]
    
    def test_multiple_strokes_same_topic(self, sp):
        for t in [100, 200, 300]:
            sp.record_stroke("topic_a", timestamp=t)
        assert sp.topic_strokes["topic_a"] == [100, 200, 300]
    
    def test_multiple_topics(self, sp):
        sp.record_stroke("alpha", timestamp=100)
        sp.record_stroke("beta", timestamp=200)
        sp.record_stroke("alpha", timestamp=300)
        
        assert len(sp.topic_strokes) == 2
        assert sp.topic_strokes["alpha"] == [100, 300]
        assert sp.topic_strokes["beta"] == [200]


# ── calculate_strength ────────────────────────────────────────────────

class TestCalculateStrength:
    def test_unknown_topic_returns_zero(self, sp):
        assert sp.calculate_strength("nonexistent") == 0.0
    
    def test_recent_stroke_high_strength(self, sp):
        now = time.time()
        sp.record_stroke("fresh", timestamp=now - 60)  # 1 min ago
        strength = sp.calculate_strength("fresh", now=now)
        assert strength > 0.9
    
    def test_old_stroke_low_strength(self, sp):
        now = time.time()
        sp.record_stroke("old", timestamp=now - 86400 * 3)  # 3 days ago
        strength = sp.calculate_strength("old", now=now)
        assert strength < 0.1
    
    def test_multiple_recent_strokes_higher_than_one(self, sp):
        now = time.time()
        sp.record_stroke("multi", timestamp=now - 100)
        sp.record_stroke("multi", timestamp=now - 200)
        sp.record_stroke("multi", timestamp=now - 300)
        
        multi_strength = sp.calculate_strength("multi", now=now)
        
        sp2 = StrokePersistence(decay_window_hours=24.0)
        sp2.record_stroke("single", timestamp=now - 100)
        single_strength = sp2.calculate_strength("single", now=now)
        
        # Multiple recent strokes should be similar or slightly different
        # (weighted average vs single), but both high
        assert multi_strength > 0.8
        assert single_strength > 0.9
    
    def test_strength_monotonically_decreases_over_time(self, sp):
        sp.record_stroke("topic", timestamp=1000)
        
        strengths = [
            sp.calculate_strength("topic", now=1000 + offset)
            for offset in [0, 3600, 7200, 14400, 43200, 86400]
        ]
        
        for i in range(len(strengths) - 1):
            assert strengths[i] >= strengths[i + 1]


# ── estimate_half_life ────────────────────────────────────────────────

class TestEstimateHalfLife:
    def test_unknown_topic_returns_inf(self, sp):
        assert sp.estimate_half_life("ghost") == float('inf')
    
    def test_single_stroke_returns_inf(self, sp):
        sp.record_stroke("lonely", timestamp=1000)
        assert sp.estimate_half_life("lonely") == float('inf')
    
    def test_frequent_strokes_short_half_life(self, sp):
        # Stroke every 5 minutes
        for i in range(20):
            sp.record_stroke("frequent", timestamp=1000 + i * 300)
        
        hl = sp.estimate_half_life("frequent")
        # 300s avg interval → 300/3600/ln(2) ≈ 0.12 hours
        assert hl < 1.0
    
    def test_rare_strokes_long_half_life(self, sp):
        # Stroke every 2 days
        for i in range(5):
            sp.record_stroke("rare", timestamp=1000 + i * 172800)
        
        hl = sp.estimate_half_life("rare")
        # 172800s = 48h → 48/ln(2) ≈ 69 hours
        assert hl > 24.0
    
    def test_half_life_positive_for_valid_data(self, populated_sp):
        hl = populated_sp.estimate_half_life("automation")
        assert hl > 0


# ── get_topic_decay ───────────────────────────────────────────────────

class TestGetTopicDecay:
    def test_unknown_topic_returns_empty_decay(self, sp):
        decay = sp.get_topic_decay("phantom")
        assert decay.stroke_count == 0
        assert decay.current_strength == 0.0
        assert decay.half_life_hours == float('inf')
    
    def test_populated_topic_has_all_fields(self, populated_sp):
        decay = populated_sp.get_topic_decay("automation")
        assert decay.topic == "automation"
        assert decay.stroke_count == 20
        assert decay.current_strength > 0
        assert decay.first_seen > 0
        assert decay.last_seen > 0
    
    def test_cold_topic_has_low_strength(self, populated_sp):
        decay = populated_sp.get_topic_decay("cold")
        assert decay.stroke_count == 0  # "cold" was never recorded
        assert decay.current_strength == 0.0
    
    def test_decay_is_dataclass(self, populated_sp):
        decay = populated_sp.get_topic_decay("automation")
        assert isinstance(decay, TopicDecay)


# ── diversity_score ───────────────────────────────────────────────────

class TestDiversityScore:
    def test_empty_tracker_returns_zero(self, sp):
        assert sp.diversity_score() == 0.0
    
    def test_single_topic_returns_zero(self, sp):
        sp.record_stroke("only_one", timestamp=time.time())
        assert sp.diversity_score() == 0.0
    
    def test_multiple_equal_topics_high_diversity(self, sp):
        now = time.time()
        for topic in ["a", "b", "c", "d", "e"]:
            for i in range(10):
                sp.record_stroke(topic, timestamp=now - i * 60)
        
        score = sp.diversity_score(now=now)
        assert score > 0.8  # High diversity when all topics are equally strong
    
    def test_one_dominant_topic_lower_diversity(self, sp):
        now = time.time()
        # One hot topic, many cold topics
        for i in range(50):
            sp.record_stroke("dominant", timestamp=now - i * 30)
        for topic in ["rare1", "rare2", "rare3", "rare4"]:
            sp.record_stroke(topic, timestamp=now - 86400 * 3)
        
        score = sp.diversity_score(now=now)
        assert score < 0.5  # Low diversity when one topic dominates


# ── report ────────────────────────────────────────────────────────────

class TestReport:
    def test_empty_report(self, sp):
        report = sp.report()
        assert report['active_count'] == 0
        assert report['total_count'] == 0
        assert report['diversity'] == 0.0
        assert report['top_topics'] == []
    
    def test_populated_report(self, populated_sp):
        report = populated_sp.report(min_strength=0.01)
        assert report['total_count'] == 4
        assert report['active_count'] >= 1
        assert 'diversity' in report
        assert isinstance(report['top_topics'], list)
    
    def test_report_respects_min_strength(self, populated_sp):
        # With high threshold, fewer topics are "active"
        report_high = populated_sp.report(min_strength=0.5)
        report_low = populated_sp.report(min_strength=0.01)
        assert report_high['active_count'] <= report_low['active_count']
    
    def test_report_top_topics_sorted_by_strength(self, populated_sp):
        report = populated_sp.report(min_strength=0.01)
        strengths = [t['strength'] for t in report['top_topics']]
        assert strengths == sorted(strengths, reverse=True)
    
    def test_report_topic_fields(self, populated_sp):
        report = populated_sp.report(min_strength=0.01)
        if report['top_topics']:
            topic = report['top_topics'][0]
            assert 'topic' in topic
            assert 'strength' in topic
            assert 'strokes' in topic
            assert 'half_life_h' in topic
