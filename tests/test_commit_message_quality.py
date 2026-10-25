"""Tests for iamai.commit_message_quality — commit message scoring.

Each test isolates one rule so that a regression in scoring logic
points directly at the broken check rather than at an opaque total.
"""

import pytest

from iamai.commit_message_quality import (
    score_message,
    score_history,
    _check_length,
    _check_capitalization,
    _check_trailing_period,
    _check_imperative,
    _check_vague,
)


# --- Length ---


class TestLength:
    def test_normal_subject_passes(self):
        assert _check_length("add retry_budget snippet (11 tests)") == []

    def test_exactly_72_chars_passes(self):
        subject = "a" * 72
        assert _check_length(subject) == []

    def test_over_72_chars_fails(self):
        subject = "a" * 73
        assert _check_length(subject) == ["too_long"]

    def test_very_short_fails(self):
        assert _check_length("ab") == ["too_short"]

    def test_empty_passes_length_check(self):
        # Empty is caught by other checks, not length.
        assert _check_length("") == ["too_short"]


# --- Capitalization ---


class TestCapitalization:
    def test_lowercase_start_ok(self):
        assert _check_capitalization("add feature") == []

    def test_uppercase_start_ok(self):
        assert _check_capitalization("Add feature") == []

    def test_digit_start_fails(self):
        assert _check_capitalization("3rd attempt") == ["non_alpha_start"]

    def test_symbol_start_fails(self):
        assert _check_capitalization("!fix") == ["non_alpha_start"]

    def test_empty_fails(self):
        assert _check_capitalization("") == ["empty"]


# --- Trailing Period ---


class TestTrailingPeriod:
    def test_no_period_passes(self):
        assert _check_trailing_period("add feature") == []

    def test_period_fails(self):
        assert _check_trailing_period("add feature.") == ["trailing_period"]

    def test_trailing_whitespace_then_period(self):
        assert _check_trailing_period("add feature.  ") == ["trailing_period"]


# --- Imperative Mood ---


class TestImperative:
    def test_imperative_add(self):
        assert _check_imperative("add") == []

    def test_imperative_fix(self):
        # "fix" as first word is fine (imperative); "fix" as entire
        # subject is caught by _check_vague, not here.
        assert _check_imperative("fix") == []

    def test_past_tense_fixed(self):
        assert _check_imperative("fixed") == ["past_tense"]

    def test_past_tense_updated(self):
        assert _check_imperative("updated") == ["past_tense"]

    def test_gerund_fixing(self):
        assert _check_imperative("fixing") == ["gerund"]

    def test_gerund_adding(self):
        assert _check_imperative("adding") == ["gerund"]

    def test_unrelated_word_passes(self):
        assert _check_imperative("refactor") == []


# --- Vague Subjects ---


class TestVague:
    def test_vague_update(self):
        assert _check_vague("update") == ["vague"]

    def test_vague_wip(self):
        assert _check_vague("WIP") == ["vague"]

    def test_vague_fix(self):
        assert _check_vague("fix") == ["vague"]

    def test_specific_passes(self):
        assert _check_vague("fix push race in batch loop") == []

    def test_vague_case_insensitive(self):
        assert _check_vague("Update") == ["vague"]


# --- Composite score_message ---


class TestScoreMessage:
    def test_perfect_message(self):
        result = score_message("add commit_message_quality module with tests")
        assert result["score"] == 100
        assert result["issues"] == []

    def test_typical_good_message(self):
        result = score_message("caretaker visit 80: add retry_budget snippet (11 tests)")
        assert result["score"] >= 80

    def test_past_tense_penalty(self):
        result = score_message("Fixed the bug in writer loop")
        assert "past_tense" in result["issues"]
        assert result["score"] <= 80

    def test_vague_message_heavily_penalized(self):
        result = score_message("update")
        # "update" is vague and too short (6 chars) → both fire
        # Wait, 6 chars is fine for length. Just vague.
        assert "vague" in result["issues"]
        assert result["score"] <= 80

    def test_terrible_message(self):
        result = score_message("Fixed stuff.")
        # past_tense + trailing_period = -40; "Fixed stuff." is not
        # in the vague set (that checks exact single words).
        assert result["score"] <= 60
        assert "past_tense" in result["issues"]
        assert "trailing_period" in result["issues"]

    def test_empty_message(self):
        result = score_message("")
        assert result["score"] == 0
        assert "empty" in result["issues"]

    def test_multiline_extracts_subject(self):
        msg = "add feature X\n\nThis is the body of the commit message."
        result = score_message(msg)
        assert result["subject"] == "add feature X"

    def test_too_long_subject(self):
        result = score_message("a" * 80)
        assert "too_long" in result["issues"]


# --- Batch scoring (score_history) ---


class TestScoreHistory:
    def test_empty_batch(self):
        result = score_history([])
        assert result["mean_score"] == 0
        assert result["total"] == 0

    def test_uniform_good_batch(self):
        messages = [
            "add feature X",
            "fix push race condition",
            "refactor batch loop for clarity",
        ]
        result = score_history(messages)
        assert result["mean_score"] >= 80
        assert result["total"] == 3

    def test_mixed_batch_tracks_issues(self):
        messages = [
            "add feature X",       # good
            "Fixed stuff.",         # bad
            "update",               # vague
        ]
        result = score_history(messages)
        assert result["total"] == 3
        assert "past_tense" in result["issues_count"]
        assert "vague" in result["issues_count"]

    def test_worst_message_identified(self):
        messages = ["add feature X", "Fixed stuff."]
        result = score_history(messages)
        assert result["worst"]["subject"] == "Fixed stuff."
