#!/usr/bin/env python3
"""Tests for writer_self_correction module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_self_correction import (
    SelfCorrectionResult,
    measure_self_correction,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_self_correction("")
        assert r.self_correction_index == 0.0
        assert r.classification == "uncorrected"

    def test_whitespace_only(self):
        r = measure_self_correction("   \n\n   ")
        assert r.self_correction_index == 0.0

    def test_none_like_empty(self):
        r = measure_self_correction("")
        assert r.total_sentences == 0

    def test_single_word(self):
        r = measure_self_correction("Hello.")
        assert r.self_correction_index == 0.0
        assert r.classification == "uncorrected"

    def test_no_correction_text(self):
        r = measure_self_correction("The sky is blue. Water is wet.")
        assert r.self_correction_index == 0.0
        assert r.explicit_correction_count == 0
        assert r.reformulation_count == 0
        assert r.retraction_count == 0


# ── uncorrected prose ──────────────────────────────────────────


class TestUncorrectedProse:
    PLAIN = (
        "The concept of justice involves fairness and equity. "
        "Mathematical proofs require logical deduction from axioms. "
        "Philosophical arguments explore the nature of existence. "
        "Aesthetic appreciation depends on cultural context. "
        "Ethical frameworks guide moral reasoning."
    )

    def test_uncorrected_classification(self):
        r = measure_self_correction(self.PLAIN)
        assert r.classification == "uncorrected"
        assert r.self_correction_index < 0.03

    def test_zero_correction_counts(self):
        r = measure_self_correction(self.PLAIN)
        assert r.explicit_correction_count == 0
        assert r.reformulation_count == 0
        assert r.retraction_count == 0
        assert r.precision_escalation_count == 0
        assert r.scope_narrowing_count == 0
        assert r.metalinguistic_count == 0

    def test_zero_diversity(self):
        r = measure_self_correction(self.PLAIN)
        assert r.self_correction_diversity == 0.0


# ── explicit correction markers ────────────────────────────────


class TestExplicitCorrection:
    TEXT = (
        "The process, or rather the subprocess, handles cleanup. "
        "The variable, I mean the constant, is defined at compile time. "
        "The function, that is the method, returns a boolean value. "
        "The result, more precisely the final result, is stored in cache. "
        "The error, more accurately the exception, propagates upward."
    )

    def test_explicit_count(self):
        r = measure_self_correction(self.TEXT)
        assert r.explicit_correction_count >= 5

    def test_explicit_rate_positive(self):
        r = measure_self_correction(self.TEXT)
        assert r.explicit_correction_rate > 0.0

    def test_not_uncorrected(self):
        r = measure_self_correction(self.TEXT)
        assert r.classification != "uncorrected"


# ── reformulation markers ──────────────────────────────────────


class TestReformulation:
    TEXT = (
        "The algorithm is inefficient. In other words, it wastes resources. "
        "The data structure, to put it differently, is poorly organized. "
        "The interface, put another way, lacks clarity. "
        "The codebase, stated differently, needs refactoring. "
        "The system, to rephrase, is fundamentally broken."
    )

    def test_reformulation_count(self):
        r = measure_self_correction(self.TEXT)
        assert r.reformulation_count >= 5

    def test_reformulation_rate(self):
        r = measure_self_correction(self.TEXT)
        assert r.reformulation_rate > 0.0


# ── retraction markers ─────────────────────────────────────────


class TestRetraction:
    TEXT = (
        "The meeting is on Tuesday. Scratch that, it's on Wednesday. "
        "We need five engineers. Forget that, we need eight. "
        "The server crashed at midnight. Disregard, it was 2 AM. "
        "The bug is in module A. Ignore that, it's in module B. "
        "He arrived at noon. Never mind, he hasn't arrived yet."
    )

    def test_retraction_count(self):
        r = measure_self_correction(self.TEXT)
        assert r.retraction_count >= 5

    def test_retraction_rate(self):
        r = measure_self_correction(self.TEXT)
        assert r.retraction_rate > 0.0


# ── precision escalation ───────────────────────────────────────


class TestPrecisionEscalation:
    TEXT = (
        "The molecule binds to the receptor, or more specifically to "
        "the alpha subunit. The reaction occurs at body temperature, "
        "or to be exact at 37.0 degrees Celsius. The sample must be "
        "pure, strictly speaking at least 99.5 percent pure. The "
        "compound is toxic, technically hepatotoxic at high doses. "
        "The effect is significant, more narrowly statistically "
        "significant at p less than 0.01."
    )

    def test_precision_count(self):
        r = measure_self_correction(self.TEXT)
        assert r.precision_escalation_count >= 4

    def test_precision_rate(self):
        r = measure_self_correction(self.TEXT)
        assert r.precision_escalation_rate > 0.0


# ── scope narrowing ────────────────────────────────────────────


class TestScopeNarrowing:
    TEXT = (
        "The theory explains all behavior, or at least most observed "
        "behavior. The model predicts outcomes, or at any rate common "
        "outcomes. The algorithm converges, at minimum under normal "
        "conditions. The proof holds, at the very least for finite "
        "cases. The hypothesis is valid, if nothing else as a "
        "starting point. The system works, at a minimum in controlled "
        "environments."
    )

    def test_scope_count(self):
        r = measure_self_correction(self.TEXT)
        assert r.scope_narrowing_count >= 5

    def test_scope_rate(self):
        r = measure_self_correction(self.TEXT)
        assert r.scope_narrowing_rate > 0.0


# ── metalinguistic correction ──────────────────────────────────


class TestMetalinguistic:
    TEXT = (
        "The phenomenon, I misspoke, the observable event is "
        "well documented. The correlation, wrong word, the "
        "association is statistically significant. The theory, "
        "poor choice of words, the framework is widely accepted. "
        "The conclusion, let me put that better, the tentative "
        "finding requires replication."
    )

    def test_metalinguistic_count(self):
        r = measure_self_correction(self.TEXT)
        assert r.metalinguistic_count >= 3

    def test_metalinguistic_rate(self):
        r = measure_self_correction(self.TEXT)
        assert r.metalinguistic_rate > 0.0


# ── composite index properties ─────────────────────────────────


class TestCompositeProperties:
    def test_index_range(self):
        """Index should always be between 0 and 1."""
        texts = [
            "Plain text with no corrections at all.",
            "This, or rather that, is the point. In other words, "
            "the thing. Scratch that. More precisely, the concept. "
            "Or at least the idea.",
        ]
        for t in texts:
            r = measure_self_correction(t)
            assert 0.0 <= r.self_correction_index <= 1.0

    def test_more_corrections_higher_index(self):
        """Text with more corrections should have a higher index."""
        low = (
            "The sky is blue. The grass is green. The sun rises "
            "in the east. Water flows downhill. Birds fly south."
        )
        high = (
            "The sky, or rather the atmosphere, is blue. The grass, "
            "I mean the vegetation, is green. The sun, more precisely "
            "the star Sol, rises in the east. Water, or to be exact "
            "H2O, flows downhill. Birds, in other words avian species, "
            "fly south."
        )
        r_low = measure_self_correction(low)
        r_high = measure_self_correction(high)
        assert r_high.self_correction_index > r_low.self_correction_index

    def test_diversity_increases_index(self):
        """Text using diverse correction forms should score higher."""
        repetitive = (
            "The thing, or rather the object, is red. The item, "
            "or rather the entity, is large. The piece, or rather "
            "the fragment, is old."
        )
        diverse = (
            "The thing, or rather the object, is red. The item, "
            "in other words the entity, is large. The piece, more "
            "precisely the fragment, is old."
        )
        r_rep = measure_self_correction(repetitive)
        r_div = measure_self_correction(diverse)
        assert r_div.self_correction_diversity >= r_rep.self_correction_diversity


# ── classification thresholds ──────────────────────────────────


class TestClassificationThresholds:
    def test_uncorrected(self):
        r = measure_self_correction("No corrections here at all. Just plain statements.")
        assert r.classification == "uncorrected"

    def test_classification_is_string(self):
        r = measure_self_correction("Some text with or rather a correction.")
        assert isinstance(r.classification, str)

    def test_valid_classification_values(self):
        """Classification must be one of the defined values."""
        valid = {
            "uncorrected",
            "lightly_corrected",
            "moderately_corrected",
            "heavily_corrected",
            "correction_saturated",
        }
        # Test with various inputs
        texts = [
            "",
            "No corrections.",
            "This, or rather that, is it.",
            "A, or rather B. In other words C. More precisely D. "
            "Scratch that. At least E. I misspoke, F. "
            "G, or rather H. I mean J. Put another way K. "
            "Technically L. To rephrase M.",
        ]
        for t in texts:
            r = measure_self_correction(t)
            assert r.classification in valid, f"Bad class for: {t!r}"


# ── diversity index ────────────────────────────────────────────


class TestDiversity:
    def test_no_forms_zero_diversity(self):
        r = measure_self_correction("Plain declarative text.")
        assert r.self_correction_diversity == 0.0

    def test_one_form_low_diversity(self):
        r = measure_self_correction("This, or rather that, is the case.")
        assert r.self_correction_diversity > 0.0
        assert r.self_correction_diversity < 0.1

    def test_many_forms_higher_diversity(self):
        text = (
            "This, or rather that, is the case. In other words, "
            "the situation. More precisely, the phenomenon. "
            "Scratch that. Strictly speaking, the event. "
            "At least the observable. I misspoke, the measurable. "
            "To rephrase, the quantifiable. On second thought."
        )
        r = measure_self_correction(text)
        assert r.self_correction_diversity > 0.05

    def test_diversity_capped_at_one(self):
        # Even with all forms, diversity should not exceed 1.0
        text = " ".join(
            [
                "or rather", "i mean", "that is", "more precisely",
                "in other words", "to rephrase", "scratch that",
                "on second thought", "strictly speaking", "at least",
                "i misspoke", "wrong word",
            ]
        ) + "."
        r = measure_self_correction(text)
        assert r.self_correction_diversity <= 1.0


# ── edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence_with_correction(self):
        r = measure_self_correction("The thing, or rather the concept, is abstract.")
        assert r.total_sentences >= 1
        assert r.explicit_correction_count >= 1

    def test_case_insensitive(self):
        r1 = measure_self_correction("Or rather, the thing.")
        r2 = measure_self_correction("OR RATHER, the thing.")
        assert r1.explicit_correction_count == r2.explicit_correction_count

    def test_mixed_punctuation(self):
        text = "The result — or rather, the outcome — is clear. The data; I mean the evidence; supports it."
        r = measure_self_correction(text)
        assert r.explicit_correction_count >= 2

    def test_repeated_same_correction(self):
        text = "A, or rather B. C, or rather D. E, or rather F."
        r = measure_self_correction(text)
        assert r.explicit_correction_count >= 3
        # But unique forms should be small
        assert r.unique_correction_forms <= 5


# ── orthogonality to other metrics ─────────────────────────────


class TestOrthogonality:
    def test_high_hedging_low_correction(self):
        """Hedging doesn't cause self-correction."""
        hedged = (
            "It seems likely that the result may perhaps be "
            "approximately correct. The finding arguably suggests "
            "a possible correlation. It appears somewhat probable "
            "that the trend might continue."
        )
        r = measure_self_correction(hedged)
        assert r.self_correction_index < 0.05
        assert r.classification == "uncorrected"

    def test_high_conviction_with_correction(self):
        """Conviction and self-correction are independent."""
        text = (
            "The earth is round — or more precisely, an oblate "
            "spheroid. Gravity pulls things down — strictly speaking, "
            "toward the center of mass. Water boils at 100 degrees — "
            "at sea level, that is."
        )
        r = measure_self_correction(text)
        assert r.self_correction_index > 0.05


# ── details dict ───────────────────────────────────────────────


class TestDetailsDict:
    def test_details_populated(self):
        r = measure_self_correction("This, or rather that, is the case.")
        assert "explicit_correction_rate" in r.details
        assert "reformulation_rate" in r.details
        assert "retraction_rate" in r.details
        assert "precision_escalation_rate" in r.details
        assert "scope_narrowing_rate" in r.details
        assert "metalinguistic_rate" in r.details
        assert "self_correction_diversity" in r.details
        assert "self_correction_index" in r.details
        assert "classification" in r.details

    def test_details_match_result(self):
        r = measure_self_correction("Some text, or rather some prose, with corrections.")
        assert r.details["self_correction_index"] == r.self_correction_index
        assert r.details["classification"] == r.classification
        assert r.details["explicit_correction_rate"] == r.explicit_correction_rate

    def test_empty_details(self):
        r = measure_self_correction("")
        assert r.details["self_correction_index"] == 0.0
        assert r.details["classification"] == "uncorrected"


# ── sentence counting ──────────────────────────────────────────


class TestSentenceCounting:
    def test_counts_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_self_correction(text)
        assert r.total_sentences >= 3

    def test_single_sentence(self):
        r = measure_self_correction("Just one sentence here.")
        assert r.total_sentences >= 1

    def test_exclamation_sentences(self):
        text = "What a day! This is great! Let us go!"
        r = measure_self_correction(text)
        assert r.total_sentences >= 3

    def test_question_sentences(self):
        text = "Is this right? What about that? Can we proceed?"
        r = measure_self_correction(text)
        assert r.total_sentences >= 3


# ── rate calculation ───────────────────────────────────────────


class TestRateCalculation:
    def test_rate_scales_with_sentence_count(self):
        """Rate should be count / sentences * 100."""
        text = "A, or rather B. C. D. E. F."
        r = measure_self_correction(text)
        if r.total_sentences > 0 and r.explicit_correction_count > 0:
            expected = r.explicit_correction_count * 100.0 / r.total_sentences
            assert abs(r.explicit_correction_rate - round(expected, 3)) < 0.1

    def test_rate_zero_when_no_sentences(self):
        r = measure_self_correction("")
        assert r.explicit_correction_rate == 0.0
        assert r.reformulation_rate == 0.0


# ── real-world prose samples ──────────────────────────────────


class TestRealWorldProse:
    PHILOSOPHICAL = (
        "Knowledge, or rather justified true belief, has been "
        "the subject of epistemology since Plato. The Gettier "
        "problem, in other words the challenge of accidental "
        "justification, showed that the classical definition is "
        "insufficient. Perhaps, more precisely, we need a fourth "
        "condition. Or at least that is what most contemporary "
        "epistemologists argue. The debate, to put it differently, "
        "remains unresolved."
    )

    CASUAL = (
        "I saw him on Tuesday — no, wait, it was Wednesday. "
        "He was wearing that blue shirt, I mean the green one. "
        "We went to that restaurant, scratch that, the cafe on "
        "Main Street. The food was great — or at least decent "
        "enough. Never mind the dessert though."
    )

    TECHNICAL = (
        "Connect to port 443, or more specifically port 8443 if "
        "using the alternate configuration. The response, strictly "
        "speaking the HTTP 200 response, contains a JSON payload. "
        "The token, technically a JWT bearer token, expires after "
        "3600 seconds."
    )

    def test_philosophical_has_corrections(self):
        r = measure_self_correction(self.PHILOSOPHICAL)
        assert r.self_correction_index > 0.03
        assert r.explicit_correction_count >= 1
        assert r.reformulation_count >= 1

    def test_casual_has_retractions(self):
        r = measure_self_correction(self.CASUAL)
        assert r.retraction_count >= 1
        assert r.self_correction_index > 0.03

    def test_technical_has_precision(self):
        r = measure_self_correction(self.TECHNICAL)
        assert r.precision_escalation_count >= 2

    def test_all_classified(self):
        """All samples should get valid classifications."""
        for text in [self.PHILOSOPHICAL, self.CASUAL, self.TECHNICAL]:
            r = measure_self_correction(text)
            assert r.classification in {
                "uncorrected",
                "lightly_corrected",
                "moderately_corrected",
                "heavily_corrected",
                "correction_saturated",
            }


# ── heavily self-corrected prose ──────────────────────────────


class TestHeavilyCorrected:
    DENSE = (
        "The argument, or rather the thesis — in other words, "
        "the central claim — is that consciousness, more precisely "
        "phenomenal consciousness, cannot be reduced to physical "
        "processes. This, strictly speaking, is the hard problem. "
        "The explanatory gap, or to be exact the epistemic gap, "
        "remains unbridgeable. Or at least that is what Chalmers "
        "argues. The zombie thought experiment, to rephrase the "
        "conceivability argument, demonstrates that physical facts "
        "do not entail phenomenal facts. More narrowly, they do "
        "not logically necessitate them."
    )

    def test_high_index(self):
        r = measure_self_correction(self.DENSE)
        assert r.self_correction_index >= 0.15

    def test_multiple_categories_present(self):
        r = measure_self_correction(self.DENSE)
        categories_with_hits = sum(
            1
            for c in [
                r.explicit_correction_count,
                r.reformulation_count,
                r.precision_escalation_count,
                r.scope_narrowing_count,
            ]
            if c > 0
        )
        assert categories_with_hits >= 3

    def test_classification_not_uncorrected(self):
        r = measure_self_correction(self.DENSE)
        assert r.classification in (
            "moderately_corrected",
            "heavily_corrected",
            "correction_saturated",
        )


# ── result dataclass integrity ─────────────────────────────────


class TestResultDataclass:
    def test_default_values(self):
        r = SelfCorrectionResult()
        assert r.explicit_correction_count == 0
        assert r.reformulation_count == 0
        assert r.retraction_count == 0
        assert r.precision_escalation_count == 0
        assert r.scope_narrowing_count == 0
        assert r.metalinguistic_count == 0
        assert r.unique_correction_forms == 0
        assert r.self_correction_index == 0.0
        assert r.classification == "uncorrected"
        assert r.total_sentences == 0
        assert r.details == {}

    def test_return_type(self):
        r = measure_self_correction("Some text.")
        assert isinstance(r, SelfCorrectionResult)
