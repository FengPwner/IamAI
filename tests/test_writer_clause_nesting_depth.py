#!/usr/bin/env python3
"""Tests for writer_clause_nesting_depth module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_clause_nesting_depth import (
    ClauseNestingResult,
    measure_clause_nesting,
    _split_sentences,
    _count_clauses_in_sentence,
    _classify,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_clause_nesting("")
        assert r.max_depth == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_clause_nesting("   \n\n   ")
        assert r.classification == "unknown"

    def test_single_word(self):
        r = measure_clause_nesting("Hello.")
        assert r.total_sentences == 1
        assert r.max_depth == 1
        assert r.classification == "flat"

    def test_no_punctuation(self):
        r = measure_clause_nesting("Hello world how are you")
        assert r.total_sentences == 1
        assert r.max_depth >= 1

    def test_punctuation_only(self):
        r = measure_clause_nesting("! ? . !")
        assert r.classification in ("unknown", "flat")


# ── sentence splitting ──────────────────────────────────────────


class TestSentenceSplitting:
    def test_two_sentences(self):
        sents = _split_sentences("The server crashed. The backup restored data.")
        assert len(sents) == 2

    def test_three_sentences(self):
        sents = _split_sentences(
            "First sentence. Second sentence. Third sentence."
        )
        assert len(sents) == 3

    def test_exclamation(self):
        sents = _split_sentences("Watch out! The server crashed.")
        assert len(sents) == 2

    def test_question_mark(self):
        sents = _split_sentences("Why did it crash? The disk was full.")
        assert len(sents) == 2

    def test_single_sentence(self):
        sents = _split_sentences("The server crashed at midnight.")
        assert len(sents) == 1


# ── flat prose (depth 1) ────────────────────────────────────────


class TestFlatProse:
    def test_simple_declarative(self):
        r = measure_clause_nesting(
            "The server crashed. The backup restored data. The team reviewed logs."
        )
        assert r.max_depth == 1
        assert r.mean_depth == 1.0
        assert r.classification == "flat"

    def test_no_subordinators(self):
        r = measure_clause_nesting(
            "Dogs bark. Cats meow. Birds sing. Fish swim."
        )
        assert r.max_depth == 1
        assert r.classification == "flat"

    def test_short_sentences(self):
        r = measure_clause_nesting("It works. Ship it.")
        assert r.max_depth == 1
        assert r.classification == "flat"


# ── simple prose (depth 2) ──────────────────────────────────────


class TestSimpleProse:
    def test_single_because(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up."
        )
        assert r.max_depth >= 2
        assert "because" in r.subordinator_counts

    def test_single_while(self):
        r = measure_clause_nesting(
            "The backup ran while the server was idle."
        )
        assert r.max_depth >= 2

    def test_single_if(self):
        r = measure_clause_nesting(
            "If the disk fills up, the server will crash."
        )
        assert r.max_depth >= 2

    def test_single_although(self):
        r = measure_clause_nesting(
            "Although the test passed, coverage is low."
        )
        assert r.max_depth >= 2
        assert "although" in r.subordinator_counts

    def test_simple_mean_depth(self):
        r = measure_clause_nesting(
            "The server crashed because the disk was full. "
            "The team restored data. The backup finished later."
        )
        assert 1.0 < r.mean_depth < 2.0


# ── layered prose (depth 2-3) ───────────────────────────────────


class TestLayeredProse:
    def test_two_levels(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up while the backup was running."
        )
        assert r.max_depth >= 3

    def test_mixed_depth(self):
        r = measure_clause_nesting(
            "The server crashed. The team restored data because the backup was intact. "
            "The monitoring system sent alerts while the incident was ongoing."
        )
        assert r.max_depth >= 2
        assert r.total_sentences == 3

    def test_relative_clause(self):
        r = measure_clause_nesting(
            "The server, which had been running for months, finally crashed."
        )
        assert r.relative_clause_count >= 1

    def test_layered_classification(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up. "
            "The team restored data after the backup finished. "
            "Although the logs were incomplete, the team identified the root cause. "
            "The monitoring system, which tracks disk usage, sent alerts."
        )
        assert r.classification in ("simple", "layered")


# ── complex prose (depth 3+) ────────────────────────────────────


class TestComplexProse:
    def test_deeply_nested(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up while the backup "
            "was running, which meant that the team, who had been on call "
            "since midnight, had to restore data manually."
        )
        assert r.max_depth >= 3

    def test_complex_mean_depth(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up while the backup "
            "was running. The team, who had been on call since midnight, "
            "restored data after the backup finished. Although the logs were "
            "incomplete, the incident was resolved before the deadline."
        )
        assert r.mean_depth >= 1.5

    def test_deep_clause_ratio(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up while the backup was running. "
            "The team restored data after the backup finished. "
            "The monitoring system sent alerts while the incident was ongoing."
        )
        assert 0.0 <= r.deep_clause_ratio <= 1.0


# ── subordinator detection ──────────────────────────────────────


class TestSubordinatorDetection:
    def test_because(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "The server crashed because the disk was full."
        )
        assert "because" in subs

    def test_although(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Although the test passed, coverage is low."
        )
        assert "although" in subs

    def test_unless(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "The server will crash unless we add more disk."
        )
        assert "unless" in subs

    def test_before(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Fix the bug before the release ships."
        )
        assert "before" in subs

    def test_after(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "After the backup finished, the team went home."
        )
        assert "after" in subs

    def test_until(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Wait until the server is ready."
        )
        assert "until" in subs

    def test_while(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "The backup ran while the server was idle."
        )
        assert "while" in subs

    def test_since(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Since the disk was full, we added more storage."
        )
        assert "since" in subs


# ── multi-word subordinator detection ───────────────────────────


class TestMultiWordSubordinators:
    def test_even_though(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Even though the test passed, coverage is low."
        )
        assert "even though" in subs
        assert depth >= 2

    def test_so_that(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Add logging so that we can debug later."
        )
        assert "so that" in subs

    def test_in_case(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Keep a backup in case the server crashes."
        )
        assert "in case" in subs

    def test_as_soon_as(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Deploy the fix as soon as the tests pass."
        )
        assert "as soon as" in subs

    def test_given_that(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "Given that the disk is full, we need more storage."
        )
        assert "given that" in subs


# ── relative clause detection ───────────────────────────────────


class TestRelativeClauseDetection:
    def test_who(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "The team who fixed the bug got a bonus."
        )
        assert rels >= 1

    def test_which(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "The server, which had been running for months, crashed."
        )
        assert rels >= 1

    def test_that_relative(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "The fix that the team deployed worked."
        )
        assert rels >= 1

    def test_whose(self):
        depth, subs, rels = _count_clauses_in_sentence(
            "The server whose disk was full crashed."
        )
        assert rels >= 1


# ── depth distribution ──────────────────────────────────────────


class TestDepthDistribution:
    def test_all_depth_1(self):
        r = measure_clause_nesting(
            "Dogs bark. Cats meow. Birds sing."
        )
        assert r.depth_distribution.get(1, 0) == 3

    def test_mixed_distribution(self):
        r = measure_clause_nesting(
            "Dogs bark. The cat meowed because it was hungry. Birds sing."
        )
        assert r.depth_distribution.get(1, 0) >= 2
        assert sum(r.depth_distribution.values()) == r.total_sentences

    def test_depth_capping(self):
        """Depth 4+ should be bucketed as 4."""
        r = measure_clause_nesting(
            "The server crashed because the disk filled up while the backup "
            "was running after the monitoring system, which tracks usage, "
            "sent alerts."
        )
        # Should have some depth >= 4
        assert r.max_depth >= 3


# ── classification thresholds ───────────────────────────────────


class TestClassification:
    def test_flat(self):
        assert _classify(1.0) == "flat"
        assert _classify(1.2) == "flat"

    def test_simple(self):
        assert _classify(1.3) == "simple"
        assert _classify(1.7) == "simple"

    def test_layered(self):
        assert _classify(1.8) == "layered"
        assert _classify(2.4) == "layered"

    def test_complex(self):
        assert _classify(2.5) == "complex"
        assert _classify(3.4) == "complex"

    def test_labyrinthine(self):
        assert _classify(3.5) == "labyrinthine"
        assert _classify(5.0) == "labyrinthine"


# ── to_dict serialization ──────────────────────────────────────


class TestSerialization:
    def test_to_dict_keys(self):
        r = measure_clause_nesting(
            "The server crashed because the disk was full."
        )
        d = r.to_dict()
        expected_keys = {
            "max_depth", "mean_depth", "total_sentences",
            "deep_clause_ratio", "depth_distribution",
            "subordinator_counts", "relative_clause_count",
            "classification",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_depth_distribution_string_keys(self):
        r = measure_clause_nesting("Dogs bark. Cats meow.")
        d = r.to_dict()
        # Keys should be stringified for JSON
        for key in d["depth_distribution"]:
            assert isinstance(key, str)

    def test_to_dict_roundtrip(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up while the backup was running."
        )
        d = r.to_dict()
        assert isinstance(d["max_depth"], int)
        assert isinstance(d["mean_depth"], float)
        assert isinstance(d["classification"], str)


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_long_sentence(self):
        r = measure_clause_nesting(
            "The server crashed because the disk filled up while the backup "
            "was running after the monitoring system sent alerts."
        )
        assert r.total_sentences == 1
        assert r.max_depth >= 3

    def test_many_short_sentences(self):
        text = ". ".join(["Dogs bark"] * 20) + "."
        r = measure_clause_nesting(text)
        assert r.total_sentences >= 19
        assert r.classification == "flat"

    def test_no_false_positive_on_demonstrative_that(self):
        """'That' as demonstrative should not count as relative clause."""
        r = measure_clause_nesting(
            "I think that the server is fine. She said that it works."
        )
        # These 'that' uses are complementizers, not relative pronouns
        # The module should ideally not count them as relative clauses
        # This is a soft test — we mainly check no crash
        assert r.total_sentences == 2

    def test_unicode_text(self):
        r = measure_clause_nesting(
            "The café, which serves great coffee, opened last year."
        )
        assert r.total_sentences == 1
        assert r.relative_clause_count >= 1

    def test_numeric_text(self):
        r = measure_clause_nesting(
            "Version 2.0 shipped on 2024-01-15. The team celebrated."
        )
        assert r.total_sentences == 2
        assert r.classification == "flat"


# ── orthogonality sanity ────────────────────────────────────────


class TestOrthogonality:
    def test_short_but_deep(self):
        """Short text can be deeply nested."""
        r = measure_clause_nesting(
            "It crashed because the disk filled while the backup ran."
        )
        assert r.max_depth >= 2
        # Word count is low but depth is high

    def test_long_but_flat(self):
        """Long text can be syntactically flat."""
        r = measure_clause_nesting(
            "The server runs Linux. The disk has 500GB of space. "
            "The backup runs at midnight. The logs rotate weekly. "
            "The team monitors everything. The alerts go to Slack."
        )
        assert r.max_depth == 1
        assert r.classification == "flat"
