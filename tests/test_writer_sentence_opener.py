#!/usr/bin/env python3
"""Tests for writer_sentence_opener module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_sentence_opener import (
    SentenceOpenerResult,
    SentenceOpener,
    measure_sentence_openers,
    _classify_opener,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_sentence_openers("")
        assert r.diversity_index == 0.0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_sentence_openers("   \n\n   ")
        assert r.classification == "unknown"

    def test_single_sentence(self):
        r = measure_sentence_openers("The server crashed.")
        assert r.total_sentences == 1
        assert r.diversity_index == 0.0

    def test_no_period(self):
        r = measure_sentence_openers("Hello world")
        assert r.total_sentences == 1


# ── opener classification ───────────────────────────────────────


class TestOpenerClassification:
    def test_subject_pronoun_i(self):
        o = _classify_opener("I think the server crashed.")
        assert o.category == "subject_pronoun"
        assert o.first_word == "I"

    def test_subject_pronoun_we(self):
        o = _classify_opener("We deployed the fix yesterday.")
        assert o.category == "subject_pronoun"

    def test_subject_pronoun_they(self):
        o = _classify_opener("They never checked the logs.")
        assert o.category == "subject_pronoun"

    def test_determiner_the(self):
        o = _classify_opener("The server crashed at midnight.")
        assert o.category == "determiner"

    def test_determiner_a(self):
        o = _classify_opener("A new bug appeared in the logs.")
        assert o.category == "determiner"

    def test_determiner_this(self):
        o = _classify_opener("This approach has limitations.")
        assert o.category == "determiner"

    def test_adverb_ly(self):
        o = _classify_opener("Suddenly, the lights went out.")
        assert o.category == "adverb"

    def test_adverb_however(self):
        o = _classify_opener("However, the fix was incomplete.")
        assert o.category == "adverb"

    def test_adverb_meanwhile(self):
        o = _classify_opener("Meanwhile, the backup system kicked in.")
        assert o.category == "adverb"

    def test_preposition_in(self):
        o = _classify_opener("In the datacenter, servers hum quietly.")
        assert o.category == "preposition"

    def test_after_as_subordinator(self):
        o = _classify_opener("After the crash, we rebooted everything.")
        # 'after' is classified as subordinator (checked before preposition)
        assert o.category == "subordinator"

    def test_conjunction_and(self):
        o = _classify_opener("And then the server crashed.")
        assert o.category == "conjunction"

    def test_conjunction_but(self):
        o = _classify_opener("But the logs told a different story.")
        assert o.category == "conjunction"

    def test_subordinator_if(self):
        o = _classify_opener("If the load exceeds capacity, the breaker trips.")
        assert o.category == "subordinator"

    def test_subordinator_because(self):
        o = _classify_opener("Because the disk was full, writes failed.")
        assert o.category == "subordinator"

    def test_subordinator_while(self):
        o = _classify_opener("While the system rebooted, users waited.")
        assert o.category == "subordinator"

    def test_other_noun(self):
        o = _classify_opener("Servers require constant maintenance.")
        assert o.category == "other"

    def test_other_adjective(self):
        o = _classify_opener("Critical errors flooded the log.")
        assert o.category == "other"

    def test_other_number(self):
        o = _classify_opener("42 servers went offline simultaneously.")
        assert o.category == "other"


# ── uniform openers (low diversity) ─────────────────────────────


class TestUniformOpeners:
    def test_all_subject_pronouns(self):
        text = (
            "I checked the logs. "
            "I found the error. "
            "I fixed the bug. "
            "I deployed the patch. "
            "I closed the ticket."
        )
        r = measure_sentence_openers(text)
        assert r.subject_pronoun_count == 5
        assert r.subject_pronoun_frac == 1.0
        assert r.diversity_index == 0.0
        assert r.classification == "uniform"

    def test_all_determiners(self):
        text = (
            "The server crashed. "
            "A backup was available. "
            "The recovery took minutes. "
            "An alert was sent. "
            "The incident was resolved."
        )
        r = measure_sentence_openers(text)
        assert r.determiner_count == 5
        assert r.determiner_frac == 1.0
        assert r.diversity_index == 0.0
        assert r.classification == "uniform"


# ── concentrated openers ────────────────────────────────────────


class TestConcentratedOpeners:
    def test_mostly_pronouns_with_one_other(self):
        text = (
            "I checked the logs. "
            "I found the error. "
            "I fixed the bug. "
            "I deployed the patch. "
            "However, the issue persisted."
        )
        r = measure_sentence_openers(text)
        assert r.subject_pronoun_count == 4
        assert r.adverb_count == 1
        assert r.dominant_category == "subject_pronoun"
        # 4:1 split across 2 categories yields high normalized entropy
        assert r.diversity_index > 0.5


# ── balanced openers ────────────────────────────────────────────


class TestBalancedOpeners:
    def test_three_categories(self):
        text = (
            "The server crashed at midnight. "
            "I checked the logs immediately. "
            "In the datacenter, alarms were sounding. "
            "But the backup system held. "
            "We restored service by dawn."
        )
        r = measure_sentence_openers(text)
        assert r.total_sentences == 5
        assert r.diversity_index > 0.3
        assert r.dominant_category is not None

    def test_diverse_mixture(self):
        text = (
            "The deployment went smoothly. "
            "However, latency spiked an hour later. "
            "In the monitoring dashboard, red flags appeared. "
            "We traced the issue to a misconfigured cache. "
            "Because the TTL was too low, stale data was served. "
            "And users started complaining."
        )
        r = measure_sentence_openers(text)
        assert r.total_sentences == 6
        assert r.determiner_count >= 1
        assert r.adverb_count >= 1
        assert r.preposition_count >= 1
        assert r.conjunction_count >= 1


# ── conjunction start rate ──────────────────────────────────────


class TestConjunctionStartRate:
    def test_no_conjunctions(self):
        text = (
            "The server crashed. "
            "The backup restored data. "
            "The incident was resolved."
        )
        r = measure_sentence_openers(text)
        assert r.conjunction_start_rate == 0.0

    def test_high_conjunction_rate(self):
        text = (
            "And the server crashed. "
            "But the backup worked. "
            "So we recovered quickly. "
            "And the users were happy."
        )
        r = measure_sentence_openers(text)
        assert r.conjunction_count == 4  # And, But, So, And
        assert r.conjunction_start_rate == 1.0

    def test_single_conjunction(self):
        text = (
            "The server crashed. "
            "But the backup worked."
        )
        r = measure_sentence_openers(text)
        assert r.conjunction_count == 1
        assert r.conjunction_start_rate == 0.5


# ── subordinator start rate ─────────────────────────────────────


class TestSubordinatorStartRate:
    def test_no_subordinators(self):
        text = (
            "The server crashed. "
            "The backup restored data."
        )
        r = measure_sentence_openers(text)
        assert r.subordinator_start_rate == 0.0

    def test_heavy_subordinators(self):
        text = (
            "If the load exceeds capacity, the breaker trips. "
            "When the disk fills up, writes fail. "
            "Because the cache was stale, users saw old data. "
            "Unless we patch now, the bug will persist."
        )
        r = measure_sentence_openers(text)
        assert r.subordinator_count == 4
        assert r.subordinator_start_rate == 1.0


# ── diversity index ─────────────────────────────────────────────


class TestDiversityIndex:
    def test_single_category_zero_diversity(self):
        text = (
            "I went to the store. "
            "I bought some milk. "
            "I came home."
        )
        r = measure_sentence_openers(text)
        assert r.diversity_index == 0.0

    def test_two_categories(self):
        text = (
            "I went to the store. "
            "The store was crowded. "
            "I bought some milk. "
            "The milk was expensive."
        )
        r = measure_sentence_openers(text)
        # Two categories at 50/50 yields normalized entropy = 1.0 (max for k=2)
        assert r.diversity_index == 1.0

    def test_max_diversity(self):
        # Seven categories, one sentence each
        text = (
            "I checked the logs. "          # subject_pronoun
            "The server crashed. "          # determiner
            "Suddenly, alarms went off. "   # adverb
            "In the datacenter, lights flickered. "  # preposition
            "And the backup kicked in. "    # conjunction
            "If we act fast, we recover. "  # subordinator
            "Servers need constant care."   # other
        )
        r = measure_sentence_openers(text)
        assert r.diversity_index > 0.9

    def test_diversity_range(self):
        text = "The server crashed. I checked the logs. We found the bug."
        r = measure_sentence_openers(text)
        assert 0.0 <= r.diversity_index <= 1.0


# ── classification ──────────────────────────────────────────────


class TestClassification:
    def test_uniform_classification(self):
        text = "I ate. I slept. I coded. I deployed. I monitored."
        r = measure_sentence_openers(text)
        assert r.classification == "uniform"

    def test_varied_classification(self):
        text = (
            "I checked the logs. "
            "The server crashed. "
            "Suddenly, alarms went off. "
            "In the datacenter, lights flickered. "
            "And the backup kicked in. "
            "If we act fast, we recover. "
            "Servers need constant care."
        )
        r = measure_sentence_openers(text)
        assert r.classification in ("diverse", "varied")


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_exclamation_sentences(self):
        r = measure_sentence_openers("Stop! Help! The server is down!")
        assert r.total_sentences == 3

    def test_question_sentences(self):
        r = measure_sentence_openers("What happened? Who deployed? When?")
        assert r.total_sentences == 3

    def test_mixed_punctuation(self):
        text = "The server crashed! What happened? I checked the logs."
        r = measure_sentence_openers(text)
        assert r.total_sentences == 3

    def test_long_text(self):
        sentences = ["The server processed request number %d." % i for i in range(100)]
        text = " ".join(sentences)
        r = measure_sentence_openers(text)
        assert r.total_sentences == 100
        assert r.determiner_count == 100

    def test_single_word_sentences(self):
        r = measure_sentence_openers("Stop. Wait. Go.")
        assert r.total_sentences == 3

    def test_empty_sentences_ignored(self):
        text = "The server crashed.   The backup worked."
        r = measure_sentence_openers(text)
        assert r.total_sentences == 2


# ── orthogonality ───────────────────────────────────────────────


class TestOrthogonality:
    def test_short_can_be_diverse(self):
        text = "I ran. The dog followed. Suddenly, rain."
        r = measure_sentence_openers(text)
        assert r.total_sentences == 3
        assert r.diversity_index > 0.3

    def test_long_can_be_uniform(self):
        text = " ".join(["I did task number %d." % i for i in range(50)])
        r = measure_sentence_openers(text)
        assert r.total_sentences == 50
        assert r.diversity_index == 0.0

    def test_formal_text_openers(self):
        text = (
            "The experiment yielded significant results. "
            "Furthermore, the control group showed no change. "
            "In conclusion, the hypothesis was confirmed."
        )
        r = measure_sentence_openers(text)
        assert r.determiner_count >= 1
        assert r.adverb_count >= 1
        assert r.preposition_count >= 1

    def test_informal_text_openers(self):
        text = (
            "So I was like, what? "
            "And he said, no way! "
            "But then we figured it out."
        )
        r = measure_sentence_openers(text)
        assert r.conjunction_count >= 1


# ── dataclass defaults ──────────────────────────────────────────


class TestDataclassDefaults:
    def test_result_defaults(self):
        r = SentenceOpenerResult()
        assert r.diversity_index == 0.0
        assert r.total_sentences == 0
        assert r.openers == []
        assert r.dominant_category is None

    def test_opener_defaults(self):
        o = SentenceOpener()
        assert o.text == ""
        assert o.first_word == ""
        assert o.category == "other"
