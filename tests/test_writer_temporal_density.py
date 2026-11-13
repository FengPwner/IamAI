#!/usr/bin/env python3
"""Tests for writer_temporal_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_temporal_density import (
    TemporalDensityResult,
    measure_temporal_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_temporal_density("")
        assert r.temporal_density_index == 0.0
        assert r.classification == "timeless"

    def test_whitespace_only(self):
        r = measure_temporal_density("   \n\n   ")
        assert r.temporal_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_temporal_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1


# ── atemporal prose (minimal temporal language) ─────────────────


class TestAtemporalProse:
    PLAIN = (
        "The concept of justice involves fairness and equity. "
        "Mathematical proofs require logical deduction from axioms. "
        "Philosophical arguments explore the nature of existence. "
        "Aesthetic appreciation depends on cultural context. "
        "Ethical frameworks guide moral reasoning."
    )

    def test_atemporal_classification(self):
        r = measure_temporal_density(self.PLAIN)
        assert r.classification in ("timeless", "lightly_temporal")
        assert r.temporal_density_index < 0.15

    def test_low_temporal_counts(self):
        r = measure_temporal_density(self.PLAIN)
        assert r.temporal_adverb_count <= 1
        assert r.sequencing_expression_count == 0
        assert r.duration_expression_count == 0
        assert r.temporal_shift_count == 0


# ── past tense heavy prose ──────────────────────────────────────


class TestPastTenseProse:
    PAST_HEAVY = (
        "She arrived at the station and discovered that the train "
        "had already left. The platform was empty. She remembered "
        "the conversation they had yesterday. He said he would "
        "wait for her. She realized she had made a mistake. The "
        "rain started and she found shelter under the awning. "
        "A man appeared and offered his umbrella. She accepted "
        "it and thanked him. The train returned an hour later."
    )

    def test_past_heavy_classification(self):
        r = measure_temporal_density(self.PAST_HEAVY)
        assert r.classification in ("moderately_temporal", "heavily_temporal")
        assert r.past_marker_count >= 8

    def test_past_rate_positive(self):
        r = measure_temporal_density(self.PAST_HEAVY)
        assert r.past_marker_rate > 50.0

    def test_past_dominance(self):
        r = measure_temporal_density(self.PAST_HEAVY)
        assert r.past_marker_count > r.future_marker_count
        assert r.past_marker_count > r.present_marker_count


# ── present tense heavy prose ───────────────────────────────────


class TestPresentTenseProse:
    PRESENT_HEAVY = (
        "The experiment shows that heat causes expansion. Water "
        "boils at 100 degrees Celsius. The process begins when "
        "the catalyst enters the solution. The reaction produces "
        "a visible change in color. The data indicates a strong "
        "correlation between temperature and reaction rate. "
        "The researcher observes the results and records the "
        "findings. The conclusion demonstrates the hypothesis "
        "is correct."
    )

    def test_present_classification(self):
        r = measure_temporal_density(self.PRESENT_HEAVY)
        assert r.classification in ("lightly_temporal", "moderately_temporal")
        assert r.present_marker_count >= 5

    def test_present_rate_positive(self):
        r = measure_temporal_density(self.PRESENT_HEAVY)
        assert r.present_marker_rate > 30.0


# ── future tense heavy prose ────────────────────────────────────


class TestFutureTenseProse:
    FUTURE_HEAVY = (
        "The company will launch the product next quarter. Sales "
        "are expected to exceed projections. The team is going to "
        "present findings at the conference. Revenue will likely "
        "increase by fifteen percent. New markets will open as "
        "the expansion continues. The board will review the "
        "quarterly results and announce strategic decisions. "
        "Employees are set to receive updated training materials. "
        "The CEO will address shareholders in the annual meeting."
    )

    def test_future_classification(self):
        r = measure_temporal_density(self.FUTURE_HEAVY)
        assert r.classification in ("moderately_temporal", "heavily_temporal")
        assert r.future_marker_count >= 4

    def test_future_rate_positive(self):
        r = measure_temporal_density(self.FUTURE_HEAVY)
        assert r.future_marker_rate > 20.0

    def test_future_dominance(self):
        r = measure_temporal_density(self.FUTURE_HEAVY)
        assert r.future_marker_count > r.past_marker_count


# ── temporal adverbs ────────────────────────────────────────────


class TestTemporalAdverbs:
    ADVERB_HEAVY = (
        "She had recently moved to the city. Currently, she works "
        "at a small café. Previously, she lived in a rural town. "
        "Yesterday, she met an interesting stranger. Tomorrow, she "
        "plans to visit the museum. Meanwhile, her cat waits "
        "patiently at home. Later, she will call her mother. "
        "Eventually, she hopes to settle down. Already, she feels "
        "more at home here."
    )

    def test_adverb_count(self):
        r = measure_temporal_density(self.ADVERB_HEAVY)
        assert r.temporal_adverb_count >= 6

    def test_adverb_rate(self):
        r = measure_temporal_density(self.ADVERB_HEAVY)
        assert r.temporal_adverb_rate > 30.0

    def test_diverse_adverbs(self):
        r = measure_temporal_density(self.ADVERB_HEAVY)
        assert r.unique_temporal_forms >= 5


# ── sequencing expressions ──────────────────────────────────────


class TestSequencingExpressions:
    SEQUENCE_HEAVY = (
        "First, gather all the ingredients. Secondly, preheat "
        "the oven to 350 degrees. Next, mix the dry ingredients "
        "in a large bowl. Then, add the wet ingredients and stir. "
        "After that, pour the batter into the pan. Subsequently, "
        "place the pan in the oven. Finally, bake for thirty "
        "minutes. Lastly, let the cake cool before serving."
    )

    def test_sequencing_count(self):
        r = measure_temporal_density(self.SEQUENCE_HEAVY)
        assert r.sequencing_expression_count >= 5

    def test_sequencing_rate(self):
        r = measure_temporal_density(self.SEQUENCE_HEAVY)
        assert r.sequencing_expression_rate > 30.0

    def test_sequencing_classification(self):
        r = measure_temporal_density(self.SEQUENCE_HEAVY)
        assert r.classification in ("moderately_temporal", "heavily_temporal")


# ── duration expressions ────────────────────────────────────────


class TestDurationExpressions:
    DURATION_HEAVY = (
        "The negotiations lasted for three weeks. She had been "
        "waiting since Monday. During the meeting, several issues "
        "arose. Throughout the year, the team worked diligently. "
        "Over the past decade, technology changed dramatically. "
        "In the last century, populations doubled. From January "
        "to June, the project consumed all resources. Until the "
        "deadline, everyone worked around the clock. As long as "
        "the funding continued, research progressed. Every day "
        "brought new challenges."
    )

    def test_duration_count(self):
        r = measure_temporal_density(self.DURATION_HEAVY)
        assert r.duration_expression_count >= 4

    def test_duration_rate(self):
        r = measure_temporal_density(self.DURATION_HEAVY)
        assert r.duration_expression_rate > 20.0

    def test_duration_classification(self):
        r = measure_temporal_density(self.DURATION_HEAVY)
        assert r.classification in ("moderately_temporal", "heavily_temporal")


# ── frequency expressions ───────────────────────────────────────


class TestFrequencyExpressions:
    FREQUENCY_HEAVY = (
        "She always arrives early. He never misses a deadline. "
        "The team frequently meets to discuss progress. Sometimes "
        "the results surprise everyone. Occasionally, a new "
        "challenge emerges. The system rarely fails. Customers "
        "usually respond positively. The journal is published "
        "monthly. Reports are generated daily. The committee "
        "typically convenes weekly."
    )

    def test_frequency_count(self):
        r = measure_temporal_density(self.FREQUENCY_HEAVY)
        assert r.frequency_expression_count >= 6

    def test_frequency_rate(self):
        r = measure_temporal_density(self.FREQUENCY_HEAVY)
        assert r.frequency_expression_rate > 30.0


# ── temporal shift markers ──────────────────────────────────────


class TestTemporalShifts:
    SHIFT_HEAVY = (
        "The project began in March. But then the funding was "
        "delayed. Meanwhile, the team continued planning. Looking "
        "back, the decision was obvious. At the same time, "
        "competitors were advancing. However, the breakthrough "
        "changed everything. In retrospect, the pivot saved the "
        "company. Looking ahead, the roadmap is clear. From now "
        "on, the focus will be on execution. Going forward, "
        "quarterly reviews will guide strategy."
    )

    def test_shift_count(self):
        r = measure_temporal_density(self.SHIFT_HEAVY)
        assert r.temporal_shift_count >= 4

    def test_shift_rate(self):
        r = measure_temporal_density(self.SHIFT_HEAVY)
        assert r.temporal_shift_rate > 15.0

    def test_shift_classification(self):
        r = measure_temporal_density(self.SHIFT_HEAVY)
        assert r.classification in ("moderately_temporal", "heavily_temporal", "time_saturated")


# ── composite index ─────────────────────────────────────────────


class TestCompositeIndex:
    def test_high_temporal_prose(self):
        text = (
            "First, the experiment was conducted over three weeks. "
            "Meanwhile, the researchers observed the subjects daily. "
            "Previously, similar studies had failed. However, this "
            "time the results were different. The data showed that "
            "the treatment frequently improved outcomes. Eventually, "
            "the team concluded that the method works. Looking back, "
            "the key insight was timing. In the past decade, no "
            "other approach achieved comparable results. Going "
            "forward, the protocol will be adopted widely."
        )
        r = measure_temporal_density(text)
        assert r.temporal_density_index > 0.30
        assert r.classification in ("moderately_temporal", "heavily_temporal", "time_saturated")

    def test_index_range(self):
        text = "The quick brown fox jumps over the lazy dog."
        r = measure_temporal_density(text)
        assert 0.0 <= r.temporal_density_index <= 1.0

    def test_index_zero_for_atemporal(self):
        text = (
            "Blue is a color. Red is another color. Green "
            "completes the primary triad. Yellow mixes with blue "
            "to make green. Purple combines red and blue."
        )
        r = measure_temporal_density(text)
        assert r.temporal_density_index < 0.15


# ── classification boundaries ───────────────────────────────────


class TestClassification:
    def test_timeless(self):
        r = measure_temporal_density("A equals B. C equals D.")
        assert r.classification == "timeless"

    def test_all_classifications_exist(self):
        """Ensure all classification labels are valid."""
        valid = {
            "timeless",
            "lightly_temporal",
            "moderately_temporal",
            "heavily_temporal",
            "time_saturated",
        }
        for text in [
            "A equals B.",
            "She arrived yesterday and left today.",
            (
                "First she arrived, then she waited. Meanwhile "
                "the rain started. Previously she had called. "
                "After that, the bus came. Finally she boarded. "
                "Eventually the journey began. Looking back, "
                "the delay was expected. In the past week, "
                "nothing had gone right. Going forward, she "
                "would plan better. From now on, always early. "
                "Over the past year, she learned patience. "
                "During the storm, she waited. Until the end, "
                "she remained calm. Every day brought lessons. "
                "Throughout the ordeal, she grew stronger."
            ),
        ]:
            r = measure_temporal_density(text)
            assert r.classification in valid


# ── orthogonality checks ───────────────────────────────────────


class TestOrthogonality:
    def test_temporal_without_causal(self):
        """Temporal language without causal markers."""
        text = (
            "First, she woke up. Then, she brushed her teeth. "
            "Next, she made breakfast. After that, she left for "
            "work. Finally, she arrived at the office."
        )
        r = measure_temporal_density(text)
        assert r.sequencing_expression_count >= 4
        # No "because", "therefore", "as a result" in the text

    def test_temporal_without_conditional(self):
        """Temporal language without conditional markers."""
        text = (
            "She arrived yesterday. She left today. Tomorrow "
            "she will return. Meanwhile, the house remained "
            "empty. Previously, it had been occupied."
        )
        r = measure_temporal_density(text)
        assert r.temporal_adverb_count >= 3
        # No "if", "unless", "provided that" in the text


# ── details dict ────────────────────────────────────────────────


class TestDetailsDict:
    def test_details_populated(self):
        r = measure_temporal_density("She arrived yesterday.")
        assert "temporal_density_index" in r.details
        assert "classification" in r.details
        assert "past_marker_rate" in r.details
        assert "present_marker_rate" in r.details
        assert "future_marker_rate" in r.details
        assert "temporal_adverb_rate" in r.details
        assert "sequencing_expression_rate" in r.details
        assert "duration_expression_rate" in r.details
        assert "frequency_expression_rate" in r.details
        assert "temporal_shift_rate" in r.details
        assert "temporal_diversity_index" in r.details

    def test_details_match_result(self):
        r = measure_temporal_density(
            "She will arrive tomorrow. He left yesterday."
        )
        assert r.details["temporal_density_index"] == r.temporal_density_index
        assert r.details["classification"] == r.classification


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence(self):
        r = measure_temporal_density("She arrived yesterday.")
        assert r.total_sentences >= 1
        assert r.temporal_adverb_count >= 1

    def test_single_word(self):
        r = measure_temporal_density("Now.")
        assert r.total_sentences >= 1

    def test_numbers_and_dates(self):
        text = (
            "In 2024, the company was founded. By 2025, it had "
            "grown to fifty employees. Since 2020, the market "
            "had changed significantly."
        )
        r = measure_temporal_density(text)
        assert r.total_sentences >= 3

    def test_very_long_text(self):
        sentence = "She worked diligently every day. "
        text = sentence * 100
        r = measure_temporal_density(text)
        assert r.total_sentences >= 100
        assert r.frequency_expression_count >= 50

    def test_repeated_temporal_words(self):
        text = "Then she left. Then she returned. Then she left again."
        r = measure_temporal_density(text)
        assert r.temporal_adverb_count >= 3

    def test_mixed_tense_prose(self):
        text = (
            "She was a great leader. She is remembered fondly. "
            "Her legacy will endure. She had established the "
            "foundation. It continues to grow. Future generations "
            "will benefit from her vision."
        )
        r = measure_temporal_density(text)
        assert r.past_marker_count >= 2
        assert r.present_marker_count >= 1
        assert r.future_marker_count >= 1
