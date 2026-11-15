#!/usr/bin/env python3
"""Tests for writer_emphasis_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_emphasis_density import (
    EmphasisDensityResult,
    measure_emphasis_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_emphasis_density("")
        assert r.emphasis_density_index == 0.0
        assert r.classification == "unemphasized"

    def test_whitespace_only(self):
        r = measure_emphasis_density("   \n\n   ")
        assert r.emphasis_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_emphasis_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1

    def test_single_word(self):
        r = measure_emphasis_density("Hello.")
        assert r.emphasis_density_index == 0.0
        assert r.classification == "unemphasized"

    def test_no_emphasis_plain_sentence(self):
        r = measure_emphasis_density("The cat sat on the mat.")
        assert r.lexical_count == 0
        assert r.syntactic_count == 0
        assert r.rhetorical_count == 0


# ── unemphasized prose ──────────────────────────────────────────


class TestUnemphasizedProse:
    PLAIN = (
        "The committee reviewed the proposal on Tuesday. "
        "Three members voted in favor and two abstained. "
        "The project will begin next month. "
        "Budget allocation covers all departments. "
        "Staff will receive training materials by email. "
        "The next meeting is scheduled for December. "
        "Reports will be submitted quarterly. "
        "No changes to the existing policy are planned."
    )

    def test_unemphasized_classification(self):
        r = measure_emphasis_density(self.PLAIN)
        assert r.classification in ("unemphasized", "lightly_emphasized")
        assert r.emphasis_density_index < 0.15

    def test_no_lexical_emphasis(self):
        r = measure_emphasis_density(self.PLAIN)
        assert r.lexical_count == 0

    def test_no_syntactic_emphasis(self):
        r = measure_emphasis_density(self.PLAIN)
        assert r.syntactic_count == 0

    def test_no_rhetorical_emphasis(self):
        r = measure_emphasis_density(self.PLAIN)
        assert r.rhetorical_count == 0

    def test_no_typographic_emphasis(self):
        r = measure_emphasis_density(self.PLAIN)
        assert r.typographic_count == 0


# ── heavily emphasized prose ────────────────────────────────────


class TestHeavilyEmphasizedProse:
    PITCH = (
        "This is the **most critical** feature we have ever shipped. "
        "It is precisely this architecture that enables our scalability. "
        "Above all, do NOT skip the migration step. "
        "The key insight is that latency matters more than throughput. "
        "Let me emphasize: this is not optional. "
        "Note that the API contract changes in v3. "
        "It bears repeating: **never** store secrets in plaintext. "
        "The bottom line is that we MUST ship by Friday. "
        "What makes this crucial is the competitive landscape. "
        "It is essential that every team member understands the stakes. "
        "Remember that our users depend on this reliability. "
        "Make no mistake: this launch defines our quarter. "
        "The paramount concern is data integrity, not speed. "
        "I cannot stress enough how vital testing is here. "
        "Pay close attention to the error handling section."
    )

    def test_heavily_emphasized_classification(self):
        r = measure_emphasis_density(self.PITCH)
        assert r.classification in (
            "heavily_emphasized",
            "emphasis_saturated",
            "moderately_emphasized",
        )
        assert r.emphasis_density_index >= 0.15

    def test_high_lexical_count(self):
        r = measure_emphasis_density(self.PITCH)
        assert r.lexical_count >= 5

    def test_high_syntactic_count(self):
        r = measure_emphasis_density(self.PITCH)
        assert r.syntactic_count >= 1

    def test_high_typographic_count(self):
        r = measure_emphasis_density(self.PITCH)
        assert r.typographic_count >= 2

    def test_high_rhetorical_count(self):
        r = measure_emphasis_density(self.PITCH)
        assert r.rhetorical_count >= 3

    def test_diversity_nonzero(self):
        r = measure_emphasis_density(self.PITCH)
        assert r.emphasis_diversity_index > 0.0


# ── lexical emphasis ────────────────────────────────────────────


class TestLexicalEmphasis:
    def test_crucial(self):
        r = measure_emphasis_density("This is a crucial decision.")
        assert r.lexical_count >= 1

    def test_critical(self):
        r = measure_emphasis_density("The critical path runs through auth.")
        assert r.lexical_count >= 1

    def test_essential(self):
        r = measure_emphasis_density("Testing is essential for reliability.")
        assert r.lexical_count >= 1

    def test_paramount(self):
        r = measure_emphasis_density("Security is paramount in this system.")
        assert r.lexical_count >= 1

    def test_above_all(self):
        r = measure_emphasis_density("Above all, keep it simple.")
        assert r.lexical_count >= 1

    def test_most_importantly(self):
        r = measure_emphasis_density("Most importantly, the data must be consistent.")
        assert r.lexical_count >= 1

    def test_key_point(self):
        r = measure_emphasis_density("The key point is that latency is bounded.")
        assert r.lexical_count >= 1

    def test_bottom_line(self):
        r = measure_emphasis_density("The bottom line is that users need trust.")
        assert r.lexical_count >= 1

    def test_noteworthy(self):
        r = measure_emphasis_density("A noteworthy aspect is the caching layer.")
        assert r.lexical_count >= 1

    def test_multiple_lexical_markers(self):
        text = (
            "This is a crucial and essential feature. "
            "The critical insight is paramount. "
            "A vital and noteworthy improvement."
        )
        r = measure_emphasis_density(text)
        assert r.lexical_count >= 5


# ── syntactic emphasis ──────────────────────────────────────────


class TestSyntacticEmphasis:
    def test_it_cleft(self):
        r = measure_emphasis_density(
            "It was precisely this design that caused the failure."
        )
        assert r.syntactic_count >= 1

    def test_what_cleft(self):
        r = measure_emphasis_density(
            "What makes this important is the scale of impact."
        )
        assert r.syntactic_count >= 1

    def test_do_support(self):
        r = measure_emphasis_density("I do believe this approach is correct.")
        assert r.syntactic_count >= 1

    def test_not_only_but_also(self):
        r = measure_emphasis_density(
            "Not only does it scale, but also it reduces latency."
        )
        assert r.syntactic_count >= 1

    def test_never_fronting(self):
        r = measure_emphasis_density("Never have I seen such poor performance.")
        assert r.syntactic_count >= 1

    def test_under_no_circumstances(self):
        r = measure_emphasis_density(
            "Under no circumstances should you delete the backup."
        )
        assert r.syntactic_count >= 1

    def test_in_no_way(self):
        r = measure_emphasis_density(
            "This is in no way acceptable for production use."
        )
        assert r.syntactic_count >= 1


# ── typographic emphasis ────────────────────────────────────────


class TestTypographicEmphasis:
    def test_markdown_bold(self):
        r = measure_emphasis_density("This is **very important** for the team.")
        assert r.typographic_count >= 1

    def test_markdown_italic(self):
        r = measure_emphasis_density("This is *really* the key issue.")
        assert r.typographic_count >= 1

    def test_all_caps_word(self):
        r = measure_emphasis_density("You MUST complete this step first.")
        assert r.typographic_count >= 1

    def test_exclamation(self):
        r = measure_emphasis_density("Deploy now! The deadline is today!")
        assert r.typographic_count >= 2

    def test_multiple_typographic(self):
        text = (
            "This is **critical** and MUST be reviewed. "
            "The *key* issue is performance! "
            "Do NOT skip this step!"
        )
        r = measure_emphasis_density(text)
        assert r.typographic_count >= 4

    def test_plain_text_no_typographic(self):
        text = (
            "The process runs automatically. "
            "Results appear in the output directory. "
            "No manual intervention is required."
        )
        r = measure_emphasis_density(text)
        assert r.typographic_count == 0


# ── rhetorical emphasis ─────────────────────────────────────────


class TestRhetoricalEmphasis:
    def test_note_that(self):
        r = measure_emphasis_density("Note that this parameter is required.")
        assert r.rhetorical_count >= 1

    def test_bear_in_mind(self):
        r = measure_emphasis_density("Bear in mind that backups are encrypted.")
        assert r.rhetorical_count >= 1

    def test_keep_in_mind(self):
        r = measure_emphasis_density("Keep in mind the latency constraints.")
        assert r.rhetorical_count >= 1

    def test_it_bears_emphasizing(self):
        r = measure_emphasis_density("It bears emphasizing that auth tokens expire.")
        assert r.rhetorical_count >= 1

    def test_worth_noting(self):
        r = measure_emphasis_density("Worth noting that the cache invalidates hourly.")
        assert r.rhetorical_count >= 1

    def test_pay_attention(self):
        r = measure_emphasis_density("Pay close attention to the error codes.")
        assert r.rhetorical_count >= 1

    def test_make_no_mistake(self):
        r = measure_emphasis_density("Make no mistake: this is a breaking change.")
        assert r.rhetorical_count >= 1

    def test_remember_that(self):
        r = measure_emphasis_density("Remember that the index rebuilds overnight.")
        assert r.rhetorical_count >= 1

    def test_do_not_forget(self):
        r = measure_emphasis_density("Do not forget to update the changelog.")
        assert r.rhetorical_count >= 1

    def test_the_point_is(self):
        r = measure_emphasis_density("The point is that consistency matters.")
        assert r.rhetorical_count >= 1

    def test_triple_repetition(self):
        r = measure_emphasis_density("Never never never deploy without tests.")
        assert r.rhetorical_count >= 1


# ── classification thresholds ────────────────────────────────────


class TestClassificationThresholds:
    def test_unemphasized(self):
        text = "The server runs the process. The output goes to a file. Done."
        r = measure_emphasis_density(text)
        assert r.classification == "unemphasized"

    def test_lightly_emphasized(self):
        text = (
            "The process runs on the server every morning. "
            "Output is logged to a file in the data directory. "
            "Results are formatted as JSON for downstream consumption. "
            "Configuration is handled automatically via environment variables. "
            "No manual intervention is needed under normal operation. "
            "The scheduler checks health endpoints before dispatching. "
            "Errors are written to stderr and captured by the logger. "
            "Restart behavior is idempotent by design. "
            "The backoff strategy on failure uses exponential delay. "
            "Logs rotate weekly and compress to gzip."
        )
        r = measure_emphasis_density(text)
        assert r.classification in ("unemphasized", "lightly_emphasized")

    def test_moderately_emphasized(self):
        text = (
            "This is a crucial component of the system. "
            "Note that the cache layer is essential for performance. "
            "It bears emphasizing that data integrity is paramount. "
            "The key insight is that latency must stay bounded. "
            "Above all, ensure backups are current. "
            "The critical path runs through authentication. "
            "Pay attention to the error handling section. "
            "This is **the** most important migration step."
        )
        r = measure_emphasis_density(text)
        assert r.emphasis_density_index >= 0.15

    def test_emphasis_saturated(self):
        text = (
            "This is the **most critical** and **essential** feature. "
            "It is CRUCIAL that you understand this VITAL point. "
            "Above all, the paramount concern is absolutely critical. "
            "Make no mistake: this is the single most important thing. "
            "Note that this fundamental, pivotal decision is non-negotiable. "
            "It bears emphasizing how incredibly vital this is. "
            "The key point, the critical insight, the essential truth: "
            "you MUST NOT skip this step! NEVER do this! "
            "Remember that the bottom line is that this is indispensable. "
            "Pay close attention to every crucial, essential detail."
        )
        r = measure_emphasis_density(text)
        assert r.emphasis_density_index >= 0.35


# ── rates ────────────────────────────────────────────────────────


class TestRates:
    def test_rates_scale_with_sentences(self):
        short = "This is crucial. Note that it matters."
        r = measure_emphasis_density(short)
        assert r.lexical_rate > 0 or r.rhetorical_rate > 0
        assert r.total_sentences == 2

    def test_rate_zero_for_plain_text(self):
        text = "The file exists. The process completed. The output was saved."
        r = measure_emphasis_density(text)
        assert r.lexical_rate == 0.0
        assert r.syntactic_rate == 0.0
        assert r.rhetorical_rate == 0.0


# ── composite and diversity ──────────────────────────────────────


class TestComposite:
    def test_composite_range(self):
        texts = [
            "Plain text with no emphasis at all.",
            "This is **crucial** and essential. Note that it is paramount.",
            "NEVER skip this CRITICAL step! It bears emphasizing!",
        ]
        for text in texts:
            r = measure_emphasis_density(text)
            assert 0.0 <= r.emphasis_density_index <= 1.0

    def test_diversity_range(self):
        texts = [
            "Plain text.",
            "This is crucial and essential and vital and paramount.",
        ]
        for text in texts:
            r = measure_emphasis_density(text)
            assert 0.0 <= r.emphasis_diversity_index <= 1.0

    def test_more_emphasis_higher_index(self):
        plain = (
            "The committee met on Tuesday. "
            "Three proposals were reviewed. "
            "The budget was approved for next quarter. "
            "Staff will receive updated guidelines. "
            "The next meeting is in December."
        )
        emphasized = (
            "The **crucial** committee meeting was pivotal. "
            "Note that three essential proposals were reviewed. "
            "It bears emphasizing that the budget is paramount. "
            "Above all, staff MUST receive vital guidelines. "
            "The critical next meeting is non-negotiable."
        )
        r_plain = measure_emphasis_density(plain)
        r_emph = measure_emphasis_density(emphasized)
        assert r_emph.emphasis_density_index > r_plain.emphasis_density_index

    def test_diversity_increases_with_variety(self):
        low_div = "This is crucial. Another crucial point. Crucial again."
        high_div = (
            "This is crucial and essential and vital. "
            "The paramount and pivotal concern is noteworthy. "
            "An imperative and compelling argument."
        )
        r_low = measure_emphasis_density(low_div)
        r_high = measure_emphasis_density(high_div)
        assert r_high.emphasis_diversity_index >= r_low.emphasis_diversity_index


# ── orthogonality ────────────────────────────────────────────────


class TestOrthogonality:
    def test_emphasis_without_conviction(self):
        """Emphasized text can be uncertain (low conviction)."""
        text = (
            "It is crucial to note that this might possibly be relevant. "
            "The essential point, perhaps, is that results may vary. "
            "Note that the vital finding could tentatively suggest something."
        )
        r = measure_emphasis_density(text)
        assert r.lexical_count >= 3
        assert r.rhetorical_count >= 1

    def test_emphasis_without_gradation(self):
        """Emphasized text need not use degree language."""
        text = (
            "Note that this is the key issue. "
            "The point is that auth tokens expire. "
            "Make no mistake: the API contract changes."
        )
        r = measure_emphasis_density(text)
        assert r.rhetorical_count >= 2
        # No comparatives, superlatives, intensifiers needed


# ── metadata ─────────────────────────────────────────────────────


class TestMetadata:
    def test_total_sentences_nonzero(self):
        r = measure_emphasis_density("One sentence. Two sentences.")
        assert r.total_sentences == 2

    def test_details_dict_populated(self):
        r = measure_emphasis_density(
            "This is crucial. Note that it matters. **Important**!"
        )
        assert "emphasis_density_index" in r.details
        assert "classification" in r.details
        assert "lexical_rate" in r.details

    def test_result_dataclass_defaults(self):
        r = EmphasisDensityResult()
        assert r.lexical_count == 0
        assert r.emphasis_density_index == 0.0
        assert r.classification == "unemphasized"
        assert r.details == {}
