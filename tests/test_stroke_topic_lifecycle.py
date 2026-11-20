"""Tests for stroke_topic_lifecycle module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.stroke_topic_lifecycle import (
    extract_tokens,
    build_mention_map,
    compute_momentum,
    classify_phase,
    classify_stream_pattern,
    compute_fixation_ratio,
    lifecycle_report,
    lifecycle_delta,
)


# ---------------------------------------------------------------------------
# extract_tokens
# ---------------------------------------------------------------------------


class TestExtractTokens:
    def test_basic_extraction(self):
        tokens = extract_tokens("hello world testing things")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens
        assert "things" in tokens

    def test_short_words_filtered(self):
        tokens = extract_tokens("the cat sat on a big red car")
        # "cat", "sat", "car" are 3 letters — filtered
        # "big" is 3 — filtered
        assert "cat" not in tokens
        assert "big" not in tokens

    def test_stopwords_removed(self):
        tokens = extract_tokens("that this through during about before")
        assert len(tokens) == 0

    def test_punctuation_stripped(self):
        tokens = extract_tokens("hello, world! testing? (things)")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens
        assert "things" in tokens

    def test_case_insensitive(self):
        tokens = extract_tokens("Hello WORLD Testing")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens

    def test_empty_string(self):
        tokens = extract_tokens("")
        assert tokens == set()

    def test_only_stopwords(self):
        tokens = extract_tokens("that this from into")
        assert len(tokens) == 0

    def test_only_short_words(self):
        tokens = extract_tokens("the a is on")
        assert len(tokens) == 0


# ---------------------------------------------------------------------------
# build_mention_map
# ---------------------------------------------------------------------------


class TestBuildMentionMap:
    def test_basic_mapping(self):
        token_sets = [
            {"python", "code"},
            {"python", "data"},
            {"rust", "code"},
        ]
        result = build_mention_map(token_sets)
        assert result["python"] == [0, 1]
        assert result["code"] == [0, 2]
        assert result["data"] == [1]
        assert result["rust"] == [2]

    def test_empty_input(self):
        result = build_mention_map([])
        assert result == {}

    def test_single_stroke(self):
        result = build_mention_map([{"alpha", "beta"}])
        assert result["alpha"] == [0]
        assert result["beta"] == [0]

    def test_no_overlap(self):
        result = build_mention_map([{"alpha"}, {"beta"}, {"gamma"}])
        assert result["alpha"] == [0]
        assert result["beta"] == [1]
        assert result["gamma"] == [2]

    def test_all_same(self):
        result = build_mention_map([{"topic"}] * 5)
        assert result["topic"] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# compute_momentum
# ---------------------------------------------------------------------------


class TestComputeMomentum:
    def test_empty_mentions(self):
        assert compute_momentum([], 10) == 0.0

    def test_zero_strokes(self):
        assert compute_momentum([0], 0) == 0.0

    def test_recent_mention_high(self):
        # Single mention at the last stroke
        mom = compute_momentum([9], 10)
        assert mom > 0.0

    def test_old_mention_lower(self):
        # Single mention at the first stroke
        mom_old = compute_momentum([0], 10)
        mom_new = compute_momentum([9], 10)
        assert mom_new > mom_old

    def test_all_strokes_maximum(self):
        # Every stroke mentions the topic
        mom = compute_momentum(list(range(10)), 10)
        assert mom == 1.0

    def test_momentum_range(self):
        mom = compute_momentum([0, 3, 7], 10)
        assert 0.0 <= mom <= 1.0

    def test_custom_decay(self):
        # Higher decay = faster falloff
        mom_low = compute_momentum([5], 10, decay=0.01)
        mom_high = compute_momentum([5], 10, decay=0.5)
        # With higher decay, a mid-stream mention loses more momentum
        assert mom_low > mom_high

    def test_multiple_recent_mentions(self):
        mom = compute_momentum([7, 8, 9], 10)
        assert mom > 0.2

    def test_single_mention_first(self):
        mom = compute_momentum([0], 100, decay=0.05)
        assert mom < 0.01  # Very low — ancient mention


# ---------------------------------------------------------------------------
# classify_phase
# ---------------------------------------------------------------------------


class TestClassifyPhase:
    def test_empty_mentions_dormant(self):
        assert classify_phase([], 100, 0.0) == "dormant"

    def test_old_mentions_dormant(self):
        # All mentions in the first 20% of a 100-stroke window
        indices = [0, 1, 2, 3, 4]
        # recency = 100 - 1 - 4 = 95, recency_frac = 0.95 > 0.3
        assert classify_phase(indices, 100, 0.1) == "dormant"

    def test_few_recent_mentions_emerging(self):
        # 2 mentions in last 10% of 100-stroke window
        indices = [92, 98]
        phase = classify_phase(indices, 100, 0.3)
        assert phase == "emerging"

    def test_single_recent_mention_emerging(self):
        indices = [99]
        phase = classify_phase(indices, 100, 0.5)
        assert phase == "emerging"

    def test_growing_phase(self):
        # More mentions in second half than first half
        indices = [10, 50, 60, 70, 80, 85, 90, 95]
        # early (< 50): [10] = 1, late (>= 50): [50..95] = 7
        phase = classify_phase(indices, 100, 0.3)
        assert phase == "growing"

    def test_declining_when_early_heavy(self):
        # Many mentions early, few late
        indices = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 95]
        # early (< 50): 10, late (>= 50): 1
        phase = classify_phase(indices, 100, 0.1)
        assert phase == "declining"

    def test_peaked_with_high_momentum(self):
        # Mentions spread across the window with high momentum
        indices = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95]
        phase = classify_phase(indices, 100, 0.5)
        assert phase == "peaked"

    def test_default_low_momentum_declining(self):
        # Few mentions, low momentum, in the active zone (last 70%)
        indices = [45, 75]
        phase = classify_phase(indices, 100, 0.1)
        # recency = 100-1-75 = 24, recency_frac = 0.24 <= 0.3 (active)
        # early (< 50): [45] = 1, late (>= 50): [75] = 1 — tied
        # momentum < 0.15 -> declining
        assert phase == "declining"

    def test_default_moderate_momentum_growing(self):
        indices = [45, 75]
        phase = classify_phase(indices, 100, 0.2)
        # recency = 100-1-75 = 24, recency_frac = 0.24 <= 0.3 (active)
        # early=1, late=1 — tied, momentum >= 0.15 -> growing
        assert phase == "growing"


# ---------------------------------------------------------------------------
# classify_stream_pattern
# ---------------------------------------------------------------------------


class TestClassifyStreamPattern:
    def test_empty_topics(self):
        assert classify_stream_pattern({}, 0, 0.0) == "steady_state"

    def test_fixation(self):
        phase_counts = {"growing": 3, "peaked": 2}
        result = classify_stream_pattern(phase_counts, 5, 0.6)
        assert result == "fixation"

    def test_graveyard(self):
        phase_counts = {"dormant": 8, "growing": 2}
        result = classify_stream_pattern(phase_counts, 10, 0.1)
        assert result == "graveyard"

    def test_shallow(self):
        phase_counts = {"emerging": 8, "growing": 2}
        result = classify_stream_pattern(phase_counts, 10, 0.1)
        assert result == "shallow"

    def test_healthy_cycle(self):
        phase_counts = {"peaked": 2, "growing": 3, "declining": 2, "dormant": 1}
        result = classify_stream_pattern(phase_counts, 8, 0.2)
        assert result == "healthy_cycle"

    def test_steady_state_default(self):
        phase_counts = {"growing": 3, "declining": 3, "dormant": 2}
        result = classify_stream_pattern(phase_counts, 8, 0.2)
        assert result == "steady_state"

    def test_fixation_takes_priority(self):
        # Even if graveyard conditions exist, fixation wins
        phase_counts = {"dormant": 8, "peaked": 2}
        result = classify_stream_pattern(phase_counts, 10, 0.6)
        assert result == "fixation"

    def test_graveyard_over_shallow(self):
        # Dormant > 40% and emerging > 40%
        phase_counts = {"dormant": 5, "emerging": 5}
        result = classify_stream_pattern(phase_counts, 10, 0.1)
        # graveyard checked before shallow
        assert result == "graveyard"


# ---------------------------------------------------------------------------
# compute_fixation_ratio
# ---------------------------------------------------------------------------


class TestComputeFixationRatio:
    def test_empty_mentions(self):
        assert compute_fixation_ratio({}, 100) == 0.0

    def test_zero_strokes(self):
        assert compute_fixation_ratio({"topic": [0]}, 0) == 0.0

    def test_single_topic_covers_all(self):
        # One topic in every stroke of the recent 30%
        indices = list(range(70, 100))
        result = compute_fixation_ratio({"alpha": indices}, 100)
        assert result == 1.0

    def test_no_recent_mentions(self):
        # All mentions are old
        result = compute_fixation_ratio({"alpha": [0, 1, 2]}, 100)
        assert result == 0.0

    def test_partial_coverage(self):
        mention_map = {
            "alpha": [75, 80, 85],
            "beta": [90, 95],
        }
        result = compute_fixation_ratio(mention_map, 100, recent_frac=0.3, top_n=2)
        # recent_start = 70, recent_count = 30
        # covered strokes in recent: {75, 80, 85, 90, 95} = 5
        assert abs(result - 5 / 30) < 0.01

    def test_top_n_limits(self):
        mention_map = {
            "alpha": list(range(70, 100)),
            "beta": list(range(70, 100)),
            "gamma": list(range(70, 100)),
            "delta": list(range(70, 100)),
        }
        result = compute_fixation_ratio(mention_map, 100, recent_frac=0.3, top_n=2)
        # Only top 2 considered, but they cover all recent strokes
        assert result == 1.0


# ---------------------------------------------------------------------------
# lifecycle_report
# ---------------------------------------------------------------------------


class TestLifecycleReport:
    def test_empty_input(self):
        report = lifecycle_report([])
        assert report["total_strokes"] == 0
        assert report["topic_count"] == 0
        assert report["pattern"] == "steady_state"

    def test_single_stroke(self):
        report = lifecycle_report(["testing python module"])
        assert report["total_strokes"] == 1
        assert report["topic_count"] > 0
        assert "testing" in report["topics"]

    def test_window_truncation(self):
        texts = ["alpha beta"] * 50 + ["gamma delta"] * 50
        report = lifecycle_report(texts, window=20)
        assert report["analysed_strokes"] == 20
        # Only last 20 strokes contain gamma, delta
        assert "gamma" in report["topics"]
        assert "delta" in report["topics"]

    def test_report_structure(self):
        texts = ["python coding session", "data analysis python", "rust programming"]
        report = lifecycle_report(texts)
        assert "total_strokes" in report
        assert "analysed_strokes" in report
        assert "topic_count" in report
        assert "topics" in report
        assert "phase_counts" in report
        assert "fixation_ratio" in report
        assert "pattern" in report

    def test_topic_info_structure(self):
        texts = ["python coding session", "python data analysis"]
        report = lifecycle_report(texts)
        for topic, info in report["topics"].items():
            assert "mentions" in info
            assert "momentum" in info
            assert "phase" in info
            assert "first_seen" in info
            assert "last_seen" in info
            assert "recency" in info

    def test_phase_counts_consistent(self):
        texts = ["alpha beta gamma"] * 10
        report = lifecycle_report(texts)
        total_from_phases = sum(report["phase_counts"].values())
        assert total_from_phases == report["topic_count"]

    def test_fixation_in_range(self):
        texts = ["python data"] * 20 + ["rust systems"] * 20
        report = lifecycle_report(texts)
        assert 0.0 <= report["fixation_ratio"] <= 1.0

    def test_pattern_is_valid(self):
        valid_patterns = {"healthy_cycle", "fixation", "shallow", "graveyard", "steady_state"}
        texts = ["python testing"] * 50
        report = lifecycle_report(texts)
        assert report["pattern"] in valid_patterns

    def test_repeated_content_fixation(self):
        # Same content repeated — should be fixation
        texts = ["python coding module data"] * 100
        report = lifecycle_report(texts)
        assert report["fixation_ratio"] > 0.5
        assert report["pattern"] == "fixation"

    def test_diverse_content_low_fixation(self):
        texts = []
        for i in range(100):
            # Each stroke uses completely unique words
            texts.append(f"xuniq{i:04d} yuniq{i:04d} zuniq{i:04d}")
        report = lifecycle_report(texts)
        # Every topic appears in exactly 1 stroke — fixation should be low
        assert report["fixation_ratio"] < 0.5

    def test_custom_decay(self):
        texts = ["python testing module", "data analysis python", "rust systems programming"]
        report_default = lifecycle_report(texts)
        report_custom = lifecycle_report(texts, decay=0.5)
        # Different decay may give different momentum values
        assert report_default["topic_count"] == report_custom["topic_count"]

    def test_all_stopwords(self):
        texts = ["that this through during about"]
        report = lifecycle_report(texts)
        assert report["topic_count"] == 0

    def test_mixed_content_lifecycle(self):
        # Topic that grows then declines
        texts = []
        for _ in range(10):
            texts.append("introduction opening setup")
        for _ in range(20):
            texts.append("python coding module python")
        for _ in range(10):
            texts.append("closing summary ending")
        report = lifecycle_report(texts)
        assert report["topic_count"] > 0


# ---------------------------------------------------------------------------
# lifecycle_delta
# ---------------------------------------------------------------------------


class TestLifecycleDelta:
    def test_empty_snapshots(self):
        before = lifecycle_report([])
        after = lifecycle_report([])
        delta = lifecycle_delta(before, after)
        assert delta["topic_count_change"] == 0
        assert delta["new_topics"] == []
        assert delta["lost_topics"] == []

    def test_new_topics_detected(self):
        before = lifecycle_report(["alpha beta"])
        after = lifecycle_report(["alpha beta gamma delta"])
        delta = lifecycle_delta(before, after)
        assert "gamma" in delta["new_topics"]
        assert "delta" in delta["new_topics"]

    def test_lost_topics_detected(self):
        before = lifecycle_report(["alpha beta gamma delta"])
        after = lifecycle_report(["alpha beta"])
        delta = lifecycle_delta(before, after)
        assert "gamma" in delta["lost_topics"]
        assert "delta" in delta["lost_topics"]

    def test_pattern_tracking(self):
        before = {"pattern": "fixation", "topics": {}, "fixation_ratio": 0.6}
        after = {"pattern": "healthy_cycle", "topics": {}, "fixation_ratio": 0.3}
        delta = lifecycle_delta(before, after)
        assert delta["pattern_before"] == "fixation"
        assert delta["pattern_after"] == "healthy_cycle"
        assert delta["pattern_shifted"] is True

    def test_stable_pattern(self):
        before = {"pattern": "steady_state", "topics": {}, "fixation_ratio": 0.2}
        after = {"pattern": "steady_state", "topics": {}, "fixation_ratio": 0.25}
        delta = lifecycle_delta(before, after)
        assert delta["pattern_shifted"] is False

    def test_phase_transitions(self):
        before = {
            "topics": {
                "python": {"phase": "emerging", "momentum": 0.1},
                "rust": {"phase": "growing", "momentum": 0.3},
            },
            "pattern": "steady_state",
            "fixation_ratio": 0.2,
        }
        after = {
            "topics": {
                "python": {"phase": "peaked", "momentum": 0.5},
                "rust": {"phase": "growing", "momentum": 0.35},
            },
            "pattern": "steady_state",
            "fixation_ratio": 0.25,
        }
        delta = lifecycle_delta(before, after)
        assert "python" in delta["phase_transitions"]
        assert delta["phase_transitions"]["python"]["from"] == "emerging"
        assert delta["phase_transitions"]["python"]["to"] == "peaked"
        assert "rust" not in delta["phase_transitions"]

    def test_momentum_changes(self):
        before = {
            "topics": {
                "python": {"phase": "growing", "momentum": 0.2},
            },
            "pattern": "steady_state",
            "fixation_ratio": 0.1,
        }
        after = {
            "topics": {
                "python": {"phase": "growing", "momentum": 0.5},
            },
            "pattern": "steady_state",
            "fixation_ratio": 0.1,
        }
        delta = lifecycle_delta(before, after)
        assert "python" in delta["momentum_changes"]
        assert delta["momentum_changes"]["python"] == 0.3

    def test_fixation_change(self):
        before = {"topics": {}, "pattern": "steady_state", "fixation_ratio": 0.2}
        after = {"topics": {}, "pattern": "fixation", "fixation_ratio": 0.6}
        delta = lifecycle_delta(before, after)
        assert delta["fixation_change"] == 0.4

    def test_topic_count_change(self):
        before = {
            "topics": {
                "alpha": {"phase": "growing", "momentum": 0.3},
                "beta": {"phase": "declining", "momentum": 0.1},
                "gamma": {"phase": "dormant", "momentum": 0.0},
            },
            "pattern": "steady_state",
            "fixation_ratio": 0.1,
        }
        after = {
            "topics": {
                "alpha": {"phase": "growing", "momentum": 0.3},
                "delta": {"phase": "emerging", "momentum": 0.4},
            },
            "pattern": "steady_state",
            "fixation_ratio": 0.1,
        }
        delta = lifecycle_delta(before, after)
        assert delta["topic_count_change"] == -1
        assert delta["new_topics"] == ["delta"]
        assert sorted(delta["lost_topics"]) == ["beta", "gamma"]

    def test_small_momentum_change_filtered(self):
        before = {
            "topics": {"python": {"phase": "growing", "momentum": 0.300}},
            "pattern": "steady_state",
            "fixation_ratio": 0.1,
        }
        after = {
            "topics": {"python": {"phase": "growing", "momentum": 0.301}},
            "pattern": "steady_state",
            "fixation_ratio": 0.1,
        }
        delta = lifecycle_delta(before, after)
        # Change of 0.001 is at the threshold — filtered
        assert "python" not in delta["momentum_changes"]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline(self):
        texts = [
            "python module testing framework",
            "data analysis python numpy",
            "python coding standards review",
            "rust systems programming safety",
            "data pipeline processing streams",
            "python testing coverage report",
            "rust memory safety guarantees",
            "module architecture design patterns",
            "data visualization charts graphs",
            "python deployment automation scripts",
        ]
        report = lifecycle_report(texts)
        assert report["total_strokes"] == 10
        assert report["topic_count"] > 0
        assert report["pattern"] in {
            "healthy_cycle", "fixation", "shallow", "graveyard", "steady_state"
        }

    def test_delta_pipeline(self):
        texts_before = [
            "python module testing",
            "data analysis numpy",
            "python coding standards",
        ]
        texts_after = texts_before + [
            "rust systems programming",
            "data pipeline streams",
            "python deployment automation",
        ]
        report_before = lifecycle_report(texts_before)
        report_after = lifecycle_report(texts_after)
        delta = lifecycle_delta(report_before, report_after)
        assert "rust" in delta["new_topics"] or delta["topic_count_change"] > 0

    def test_window_vs_full(self):
        texts = ["alpha beta"] * 50 + ["gamma delta epsilon"] * 50
        full = lifecycle_report(texts)
        windowed = lifecycle_report(texts, window=30)
        assert full["analysed_strokes"] == 100
        assert windowed["analysed_strokes"] == 30
        # Windowed should only see gamma, delta, epsilon
        assert "gamma" in windowed["topics"]
        assert "alpha" not in windowed["topics"]

    def test_graveyard_scenario(self):
        # Many topics introduced early, then abandoned
        texts = []
        for i in range(30):
            texts.append(f"topic{i:03d} discussion session")
        # Then only one topic for the rest
        for _ in range(70):
            texts.append("final topic conclusion summary")
        report = lifecycle_report(texts)
        # Many early topics should be dormant
        dormant_count = report["phase_counts"].get("dormant", 0)
        assert dormant_count > 5

    def test_fixation_scenario(self):
        # One topic dominates
        texts = []
        for _ in range(90):
            texts.append("python programming language features")
        for _ in range(10):
            texts.append("rust systems safety memory")
        report = lifecycle_report(texts)
        assert report["pattern"] == "fixation"

    def test_shallow_scenario(self):
        # Many topics emerge briefly then vanish
        texts = []
        for i in range(50):
            # Each stroke introduces a new unique topic
            texts.append(f"novel{i:03d} subject matter content")
        report = lifecycle_report(texts)
        # Most topics should be emerging or dormant
        assert report["topic_count"] > 20

    def test_healthy_cycle_scenario(self):
        # Topics cycle through naturally
        texts = []
        # Topic 1: emerge and peak
        for _ in range(20):
            texts.append("python programming module testing")
        # Topic 2: emerge and peak
        for _ in range(20):
            texts.append("rust systems safety memory")
        # Topic 3: emerge and peak
        for _ in range(20):
            texts.append("javascript frontend framework components")
        # Mix of everything
        for _ in range(20):
            texts.append("python rust javascript integration testing")
        # Topic 4: new emergence
        for _ in range(20):
            texts.append("golang concurrency goroutines channels")
        report = lifecycle_report(texts)
        assert report["topic_count"] > 5
        # Should not be fixation since topics rotate
        assert report["pattern"] != "fixation" or report["fixation_ratio"] > 0.5
