#!/usr/bin/env python3
"""Tests for writer_enumeration_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_enumeration_density import (
    EnumerationDensityResult,
    measure_enumeration_density,
)


# ── empty / degenerate input ────────────────────────────────────

class TestEmptyInput:
    def test_empty_string(self):
        r = measure_enumeration_density("")
        assert r.enumeration_density_index == 0.0
        assert r.classification == "continuous"

    def test_whitespace_only(self):
        r = measure_enumeration_density("   \n\n   ")
        assert r.enumeration_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_enumeration_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1


# ── plain continuous prose (no enumeration) ─────────────────────

class TestContinuousProse:
    PLAIN = (
        "The morning light crept across the floorboards, painting "
        "long amber rectangles that shifted with the hours. She sat "
        "at the kitchen table, turning a cold cup of tea in her "
        "hands, watching the garden through the window. The roses "
        "had bloomed early this year, their red petals scattered "
        "across the wet grass like small flags of surrender. A "
        "blackbird perched on the fence, tilted its head, and flew "
        "away without singing."
    )

    def test_continuous_classification(self):
        r = measure_enumeration_density(self.PLAIN)
        assert r.classification == "continuous"
        assert r.enumeration_density_index < 0.05

    def test_no_explicit_numbering(self):
        r = measure_enumeration_density(self.PLAIN)
        assert r.explicit_numbering_count == 0

    def test_no_bullet_lines(self):
        r = measure_enumeration_density(self.PLAIN)
        assert r.bullet_line_count == 0


# ── explicit numbering ──────────────────────────────────────────

class TestExplicitNumbering:
    NUMBERED = """
    Here are the steps to follow:

    1. Open the configuration file.
    2. Locate the section labeled "advanced."
    3. Change the value to "true."
    4. Save and restart the service.
    5. Verify the change took effect.
    """

    def test_detects_numbered_list(self):
        r = measure_enumeration_density(self.NUMBERED)
        assert r.explicit_numbering_count >= 4

    def test_numbering_rate_positive(self):
        r = measure_enumeration_density(self.NUMBERED)
        assert r.explicit_numbering_rate > 0

    def test_at_least_moderately_enumerated(self):
        r = measure_enumeration_density(self.NUMBERED)
        assert r.enumeration_density_index >= 0.15


# ── ordinal markers ─────────────────────────────────────────────

class TestOrdinalMarkers:
    ORDINAL = (
        "First, we need to understand the problem. Second, we "
        "should identify the root cause. Third, we propose a "
        "solution. Fourth, we implement the fix. Fifth, we "
        "validate the result. Sixth, we deploy to production. "
        "Seventh, we monitor for regressions. Eighth, we write "
        "the post-mortem. Ninth, we share lessons learned. "
        "Finally, we close the incident."
    )

    def test_detects_ordinals(self):
        r = measure_enumeration_density(self.ORDINAL)
        assert r.ordinal_marker_count >= 8

    def test_ordinal_rate_positive(self):
        r = measure_enumeration_density(self.ORDINAL)
        assert r.ordinal_marker_rate > 0


# ── sequential phrases ──────────────────────────────────────────

class TestSequentialPhrases:
    SEQUENTIAL = (
        "On the one hand, the proposal offers significant cost "
        "savings. On the other hand, it introduces operational "
        "risk. For one thing, the vendor is untested. For another "
        "thing, the timeline is aggressive. In the first place, "
        "we should question whether the savings are real. Yet "
        "another concern is the lack of documentation. Still "
        "another issue is the staffing requirement."
    )

    def test_detects_sequential(self):
        r = measure_enumeration_density(self.SEQUENTIAL)
        assert r.sequential_phrase_count >= 4

    def test_sequential_rate_positive(self):
        r = measure_enumeration_density(self.SEQUENTIAL)
        assert r.sequential_phrase_rate > 0


# ── bullet lines ────────────────────────────────────────────────

class TestBulletLines:
    BULLETS = """
    Key findings from the analysis:

    - Revenue grew 12% year over year
    - Operating margin improved to 18%
    - Customer acquisition cost decreased
    - Churn rate remained stable at 3.2%
    - Net promoter score reached 72
    """

    def test_detects_bullets(self):
        r = measure_enumeration_density(self.BULLETS)
        assert r.bullet_line_count >= 4

    def test_bullet_rate_positive(self):
        r = measure_enumeration_density(self.BULLETS)
        assert r.bullet_line_rate > 0


# ── inline lists ────────────────────────────────────────────────

class TestInlineLists:
    INLINE = (
        "The committee reviewed the budget, timeline, staffing "
        "plan, and risk assessment before making their recommendation. "
        "They considered cost, quality, delivery speed, and team "
        "capacity as the primary evaluation criteria. The final report "
        "addressed risk, mitigation, contingency planning, and "
        "timeline recovery in separate chapters."
    )

    def test_detects_inline_lists(self):
        r = measure_enumeration_density(self.INLINE)
        assert r.inline_list_count >= 2

    def test_inline_rate_positive(self):
        r = measure_enumeration_density(self.INLINE)
        assert r.inline_list_rate > 0


# ── colon-introduced lists ──────────────────────────────────────

class TestColonLists:
    COLON = (
        "The recipe requires three ingredients: flour, eggs, "
        "and butter. The sauce needs two things: cream and "
        "garlic. The garden has four sections: roses, herbs, "
        "vegetables and fruit trees."
    )

    def test_detects_colon_lists(self):
        r = measure_enumeration_density(self.COLON)
        assert r.colon_list_count >= 2

    def test_colon_rate_positive(self):
        r = measure_enumeration_density(self.COLON)
        assert r.colon_list_rate > 0


# ── enumerated paragraph ratio ─────────────────────────────────

class TestParagraphRatio:
    ALL_ENUMERATED = """
    1. Open the file in your editor.
    2. Navigate to line 42.
    3. Delete the offending code.

    1. Run the test suite.
    2. Check for failures.
    3. Fix any regressions.
    """

    NONE_ENUMERATED = (
        "The rain fell steadily throughout the afternoon. "
        "Puddles formed in the hollows of the old road. "
        "A cat sat beneath a parked car, watching the "
        "world with yellow, unblinking eyes."
    )

    def test_all_enumerated(self):
        r = measure_enumeration_density(self.ALL_ENUMERATED)
        assert r.enumerated_paragraph_ratio > 0.8

    def test_none_enumerated(self):
        r = measure_enumeration_density(self.NONE_ENUMERATED)
        assert r.enumerated_paragraph_ratio < 0.1


# ── composite index ─────────────────────────────────────────────

class TestCompositeIndex:
    def test_index_bounded_zero_to_one(self):
        texts = [
            "Simple sentence.",
            "1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n7. g\n8. h",
            "First, one thing. Second, another. Third, yet more. "
            "Fourth, still more. Fifth, even more. Sixth, and more. "
            "Seventh, more still. Eighth, the last thing.",
        ]
        for t in texts:
            r = measure_enumeration_density(t)
            assert 0.0 <= r.enumeration_density_index <= 1.0

    def test_heavy_list_higher_index(self):
        light = (
            "The garden was beautiful. Roses bloomed everywhere. "
            "The birds sang. The sun shone. It was a perfect day."
        )
        heavy = """
        Tasks for today:

        1. Review the pull request
        2. Update the documentation
        3. Fix the failing tests
        4. Deploy to staging
        5. Notify the team

        - Check performance metrics
        - Validate the migration
        - Run the smoke tests
        - Update the changelog
        - Close the ticket
        """
        r_light = measure_enumeration_density(light)
        r_heavy = measure_enumeration_density(heavy)
        assert r_heavy.enumeration_density_index > r_light.enumeration_density_index


# ── classification tiers ────────────────────────────────────────

class TestClassification:
    def test_continuous_for_plain_prose(self):
        text = (
            "She walked through the park, watching leaves fall. "
            "The air was cool, carrying the scent of damp earth. "
            "Somewhere a dog barked, and a child laughed."
        )
        r = measure_enumeration_density(text)
        assert r.classification == "continuous"

    def test_classification_is_valid_string(self):
        valid = {
            "continuous",
            "lightly_enumerated",
            "moderately_enumerated",
            "heavily_enumerated",
            "list_saturated",
        }
        r = measure_enumeration_density("Some text here. And more.")
        assert r.classification in valid

    def test_list_saturated_for_pure_list(self):
        lines = "\n".join(f"{i}. item {i}" for i in range(1, 21))
        r = measure_enumeration_density(lines)
        assert r.enumeration_density_index >= 0.35


# ── dataclass completeness ──────────────────────────────────────

class TestDataclass:
    def test_result_has_all_fields(self):
        r = measure_enumeration_density("Hello world.")
        assert hasattr(r, "explicit_numbering_rate")
        assert hasattr(r, "ordinal_marker_rate")
        assert hasattr(r, "sequential_phrase_rate")
        assert hasattr(r, "bullet_line_rate")
        assert hasattr(r, "inline_list_rate")
        assert hasattr(r, "colon_list_rate")
        assert hasattr(r, "enumerated_paragraph_ratio")
        assert hasattr(r, "enumeration_density_index")
        assert hasattr(r, "classification")
        assert hasattr(r, "explicit_numbering_count")
        assert hasattr(r, "ordinal_marker_count")
        assert hasattr(r, "sequential_phrase_count")
        assert hasattr(r, "bullet_line_count")
        assert hasattr(r, "inline_list_count")
        assert hasattr(r, "colon_list_count")
        assert hasattr(r, "enumerated_paragraphs")
        assert hasattr(r, "total_paragraphs")
        assert hasattr(r, "total_sentences")
        assert hasattr(r, "details")

    def test_details_dict_populated(self):
        r = measure_enumeration_density("First, do this. Second, do that.")
        assert "enumeration_density_index" in r.details
        assert "classification" in r.details
        assert "explicit_numbering_rate" in r.details


# ── orthogonality sanity ────────────────────────────────────────

class TestOrthogonality:
    def test_enumeration_without_complex_sentences(self):
        """Short simple sentences can still be enumerated."""
        text = "1. Red.\n2. Blue.\n3. Green.\n4. Yellow.\n5. Black."
        r = measure_enumeration_density(text)
        assert r.enumeration_density_index > 0.1

    def test_complex_prose_without_enumeration(self):
        """Complex sentences need not enumerate."""
        text = (
            "Although the committee had spent months deliberating "
            "on the matter, weighing each option against a complex "
            "matrix of financial, operational, and strategic criteria, "
            "the final decision came down to a simple question of "
            "whether the organization could afford to wait another "
            "year before modernizing its aging infrastructure."
        )
        r = measure_enumeration_density(text)
        assert r.enumeration_density_index < 0.15


# ── roman numerals ──────────────────────────────────────────────

class TestRomanNumerals:
    ROMAN = """
    The treaty had three main provisions:

    i. All parties shall cease hostilities immediately.
    ii. Prisoners of war shall be exchanged within thirty days.
    iii. A demilitarized zone shall be established along the border.
    """

    def test_detects_roman_numerals(self):
        r = measure_enumeration_density(self.ROMAN)
        assert r.explicit_numbering_count >= 2


# ── step/phase keywords ────────────────────────────────────────

class TestStepKeywords:
    STEPS = """
    Follow these steps:

    Step 1: Prepare the workspace.
    Step 2: Install dependencies.
    Step 3: Run the build.
    Step 4: Execute tests.
    Step 5: Deploy to production.
    """

    def test_detects_step_keywords(self):
        r = measure_enumeration_density(self.STEPS)
        assert r.explicit_numbering_count >= 4


# ── mixed signals ───────────────────────────────────────────────

class TestMixedSignals:
    MIXED = """
    First, let us consider the options.

    1. Accept the current proposal.
    2. Request modifications.
    3. Reject and start over.

    The key factors to evaluate:

    - Cost implications
    - Timeline impact
    - Resource requirements
    - Risk exposure

    On the one hand, option one is fastest. On the other hand,
    option three gives us more control. For one thing, speed
    matters. For another thing, quality matters too.
    """

    def test_mixed_signals_detected(self):
        r = measure_enumeration_density(self.MIXED)
        assert r.explicit_numbering_count >= 2
        assert r.ordinal_marker_count >= 1
        assert r.bullet_line_count >= 3
        assert r.sequential_phrase_count >= 3

    def test_mixed_classified_moderate_or_higher(self):
        r = measure_enumeration_density(self.MIXED)
        assert r.enumeration_density_index >= 0.15

    def test_multiple_paragraphs_enumerated(self):
        r = measure_enumeration_density(self.MIXED)
        assert r.enumerated_paragraphs >= 2


# ── then as ordinal ─────────────────────────────────────────────

class TestThenAsOrdinal:
    def test_then_detected(self):
        text = (
            "First, mix the dry ingredients. Then add the wet "
            "ingredients. Then fold in the chocolate chips. "
            "Next, pour into the pan. Then bake for thirty minutes."
        )
        r = measure_enumeration_density(text)
        assert r.ordinal_marker_count >= 3


# ── reproducibility ─────────────────────────────────────────────

class TestReproducibility:
    def test_same_input_same_output(self):
        text = (
            "1. First item.\n2. Second item.\n3. Third item.\n"
            "Finally, the conclusion is that lists are useful."
        )
        r1 = measure_enumeration_density(text)
        r2 = measure_enumeration_density(text)
        assert r1.enumeration_density_index == r2.enumeration_density_index
        assert r1.classification == r2.classification
        assert r1.explicit_numbering_count == r2.explicit_numbering_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
