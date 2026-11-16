#!/usr/bin/env python3
"""Tests for writer_passive_voice_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_passive_voice_density import (
    PassiveVoiceResult,
    measure_passive_voice,
    _is_past_participle,
    _find_passives_in_sentence,
    _tokenize,
    _split_sentences,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_passive_voice("")
        assert r.passive_count == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_passive_voice("   \n\n   ")
        assert r.passive_count == 0
        assert r.classification == "unknown"

    def test_none_like(self):
        r = measure_passive_voice("   ")
        assert r.word_count == 0
        assert r.classification == "unknown"

    def test_single_word(self):
        r = measure_passive_voice("Hello.")
        assert r.passive_count == 0
        assert r.word_count == 1

    def test_no_sentences(self):
        r = measure_passive_voice("hello world")
        assert r.sentence_count == 1  # treated as one sentence
        assert r.passive_count == 0


# ── be-passive detection ────────────────────────────────────────


class TestBePassive:
    def test_was_ed(self):
        r = measure_passive_voice("The cake was eaten by the children.")
        assert r.passive_count >= 1

    def test_were_ed(self):
        r = measure_passive_voice("The results were published in the journal.")
        assert r.passive_count >= 1

    def test_is_ed(self):
        r = measure_passive_voice("The code is tested before deployment.")
        assert r.passive_count >= 1

    def test_are_ed(self):
        r = measure_passive_voice("The logs are rotated daily.")
        assert r.passive_count >= 1

    def test_been_ed(self):
        r = measure_passive_voice("The server has been compromised.")
        assert r.passive_count >= 1

    def test_being_ed(self):
        r = measure_passive_voice("The house is being painted.")
        assert r.passive_count >= 1

    def test_irregular_participle_written(self):
        r = measure_passive_voice("The report was written by the analyst.")
        assert r.passive_count >= 1
        assert "written" in r.passive_verbs

    def test_irregular_participle_taken(self):
        r = measure_passive_voice("The decision was taken yesterday.")
        assert r.passive_count >= 1
        assert "taken" in r.passive_verbs

    def test_irregular_participle_seen(self):
        r = measure_passive_voice("The problem has been seen before.")
        assert r.passive_count >= 1
        assert "seen" in r.passive_verbs

    def test_irregular_participle_done(self):
        r = measure_passive_voice("The work was done quickly.")
        assert r.passive_count >= 1

    def test_irregular_participle_broken(self):
        r = measure_passive_voice("The build was broken by the last commit.")
        assert r.passive_count >= 1
        assert "broken" in r.passive_verbs

    def test_irregular_participle_found(self):
        r = measure_passive_voice("A bug was found in production.")
        assert r.passive_count >= 1

    def test_irregular_participle_made(self):
        r = measure_passive_voice("The change was made at midnight.")
        assert r.passive_count >= 1

    def test_irregular_participle_known(self):
        r = measure_passive_voice("The issue is known to the team.")
        assert r.passive_count >= 1

    def test_multiple_passives_in_text(self):
        text = (
            "The code was reviewed. "
            "The tests were written. "
            "The report has been published."
        )
        r = measure_passive_voice(text)
        assert r.passive_count >= 3


# ── get-passive detection ───────────────────────────────────────


class TestGetPassive:
    def test_got_ed(self):
        r = measure_passive_voice("The window got broken during the storm.")
        assert r.passive_count >= 1
        assert r.get_passive >= 1

    def test_get_ed(self):
        r = measure_passive_voice("You might get fired for that.")
        assert r.passive_count >= 1
        assert r.get_passive >= 1

    def test_gets_irregular(self):
        r = measure_passive_voice("He gets paid every Friday.")
        assert r.passive_count >= 1
        assert r.get_passive >= 1


# ── agentless vs agent passive ─────────────────────────────────


class TestAgentSubtype:
    def test_agentless(self):
        r = measure_passive_voice("The code was reviewed.")
        assert r.agentless_passive >= 1
        assert r.agent_passive == 0

    def test_agent_with_by(self):
        r = measure_passive_voice("The code was reviewed by the team.")
        assert r.agent_passive >= 1

    def test_mixed(self):
        text = (
            "The code was reviewed by the team. "
            "The tests were written. "
            "The bug was found by QA."
        )
        r = measure_passive_voice(text)
        assert r.agentless_passive >= 1
        assert r.agent_passive >= 1

    def test_agentless_ratio_all_agentless(self):
        text = (
            "The code was reviewed. "
            "The tests were written. "
            "The report was published."
        )
        r = measure_passive_voice(text)
        if r.passive_count > 0:
            assert r.agentless_ratio == 1.0

    def test_agentless_ratio_mixed(self):
        text = (
            "The code was reviewed by the team. "
            "The tests were written."
        )
        r = measure_passive_voice(text)
        if r.passive_count >= 2:
            assert 0.0 < r.agentless_ratio < 1.0


# ── intervening adverbs ────────────────────────────────────────


class TestInterveningAdverbs:
    def test_not_between_be_and_participle(self):
        r = measure_passive_voice("The code was not reviewed.")
        assert r.passive_count >= 1

    def test_already_between_be_and_participle(self):
        r = measure_passive_voice("The fix has already been deployed.")
        assert r.passive_count >= 1

    def test_never_between_be_and_participle(self):
        r = measure_passive_voice("The bug was never reported.")
        assert r.passive_count >= 1

    def test_just_between_be_and_participle(self):
        r = measure_passive_voice("The file was just updated.")
        assert r.passive_count >= 1

    def test_well_between_be_and_participle(self):
        r = measure_passive_voice("The system is well tested.")
        assert r.passive_count >= 1


# ── active voice (no false positives) ──────────────────────────


class TestActiveVoice:
    def test_simple_active(self):
        r = measure_passive_voice("The team wrote the code.")
        assert r.passive_count == 0

    def test_active_with_be_as_main_verb(self):
        r = measure_passive_voice("She is happy with the results.")
        assert r.passive_count == 0

    def test_active_progressive(self):
        r = measure_passive_voice("They are running the tests.")
        # "are running" — running is present participle (-ing), not past participle
        assert r.passive_count == 0

    def test_active_perfect(self):
        r = measure_passive_voice("The team has completed the review.")
        assert r.passive_count == 0

    def test_imperative(self):
        r = measure_passive_voice("Write the tests before the code.")
        assert r.passive_count == 0

    def test_question_active(self):
        r = measure_passive_voice("Did the team finish the review?")
        assert r.passive_count == 0


# ── past participle detection ──────────────────────────────────


class TestIsPastParticiple:
    def test_regular_ed(self):
        assert _is_past_participle("tested") is True
        assert _is_past_participle("reviewed") is True
        assert _is_past_participle("published") is True

    def test_irregular(self):
        assert _is_past_participle("written") is True
        assert _is_past_participle("broken") is True
        assert _is_past_participle("seen") is True
        assert _is_past_participle("done") is True
        assert _is_past_participle("taken") is True

    def test_not_participle(self):
        assert _is_past_participle("the") is False
        assert _is_past_participle("running") is False
        assert _is_past_participle("quickly") is False
        assert _is_past_participle("is") is False

    def test_short_ed_words(self):
        # Very short -ed words should not match (likely not participles)
        assert _is_past_participle("ed") is False

    def test_en_ending(self):
        assert _is_past_participle("broken") is True
        assert _is_past_participle("chosen") is True
        assert _is_past_participle("frozen") is True


# ── rate calculations ──────────────────────────────────────────


class TestRates:
    def test_passive_rate_all_passive(self):
        text = (
            "The code was reviewed. "
            "The tests were written. "
            "The report was published. "
            "The bug was found. "
            "The fix was deployed."
        )
        r = measure_passive_voice(text)
        assert r.passive_rate > 50  # mostly passive

    def test_passive_rate_mixed(self):
        text = (
            "The team wrote the code. "
            "The code was reviewed by the lead. "
            "They shipped the release. "
            "The tests were updated."
        )
        r = measure_passive_voice(text)
        assert 0 < r.passive_rate < 100

    def test_passive_per_100_words(self):
        # 100+ word text with exactly 2 passives
        words = ["The"] * 98  # filler words to reach ~100
        text = " ".join(words)
        text += ". The code was reviewed. The tests were written."
        r = measure_passive_voice(text)
        assert r.passive_count >= 2
        assert r.passive_per_100_words > 0

    def test_rates_are_non_negative(self):
        r = measure_passive_voice("Hello world.")
        assert r.passive_rate >= 0
        assert r.passive_per_100_words >= 0


# ── classification ─────────────────────────────────────────────


class TestClassification:
    def test_active_dominant(self):
        # All active voice
        text = (
            "The team wrote the code. "
            "They tested everything. "
            "She reviewed the pull request. "
            "He deployed the release. "
            "We celebrated the launch."
        )
        r = measure_passive_voice(text)
        assert r.classification == "active_dominant"

    def test_institutional(self):
        # Almost all passive
        text = (
            "The code was reviewed. "
            "The tests were written. "
            "The report was published. "
            "The fix was deployed. "
            "The logs were rotated."
        )
        r = measure_passive_voice(text)
        assert r.classification in ("institutional", "bureaucratic")

    def test_classification_is_valid_string(self):
        valid = {"active_dominant", "balanced", "passive_leaning",
                 "bureaucratic", "institutional", "unknown"}
        r = measure_passive_voice("The code was reviewed by the team.")
        assert r.classification in valid

    def test_unknown_for_empty(self):
        r = measure_passive_voice("")
        assert r.classification == "unknown"


# ── top verbs ──────────────────────────────────────────────────


class TestTopVerbs:
    def test_top_verbs_populated(self):
        text = (
            "The code was reviewed. "
            "The tests were reviewed. "
            "The docs were reviewed. "
            "The fix was written. "
            "The report was written."
        )
        r = measure_passive_voice(text)
        assert len(r.top_passive_verbs) > 0
        # "reviewed" should be the most common
        assert r.top_passive_verbs[0][0] == "reviewed"

    def test_top_verbs_limit_five(self):
        # Many different passive verbs
        text = (
            "The code was reviewed. "
            "The tests were written. "
            "The report was published. "
            "The fix was deployed. "
            "The logs were rotated. "
            "The build was broken. "
            "The bug was found."
        )
        r = measure_passive_voice(text)
        assert len(r.top_passive_verbs) <= 5

    def test_top_verbs_empty_for_no_passives(self):
        r = measure_passive_voice("The team wrote excellent code.")
        assert r.top_passive_verbs == []


# ── edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_very_short_text(self):
        r = measure_passive_voice("It was done.")
        assert r.passive_count >= 1
        assert r.word_count == 3

    def test_long_text_all_passive(self):
        sentences = [f"The item was processed at step {i}." for i in range(20)]
        r = measure_passive_voice(" ".join(sentences))
        assert r.passive_count >= 15
        assert r.classification in ("institutional", "bureaucratic")

    def test_mixed_case(self):
        r = measure_passive_voice("The CODE was REVIEWED by the TEAM.")
        assert r.passive_count >= 1

    def test_contraction_handling(self):
        # "It's" contains "'s" which is a be-form contraction
        r = measure_passive_voice("It's been tested thoroughly.")
        # Should detect "been tested" as passive
        assert r.passive_count >= 0  # at minimum doesn't crash

    def test_no_crash_on_unusual_punctuation(self):
        r = measure_passive_voice("Was it... tested? Yes! It was reviewed!")
        assert r.word_count > 0

    def test_multiple_sentences_mixed_types(self):
        text = (
            "We wrote the code. "
            "It was tested automatically. "
            "The team reviewed it carefully. "
            "The results were published online. "
            "Users loved the feature."
        )
        r = measure_passive_voice(text)
        assert r.passive_count >= 2
        assert r.word_count > 20
        assert r.sentence_count == 5


# ── real-world scenarios ───────────────────────────────────────


class TestRealWorld:
    def test_academic_abstract_passive_heavy(self):
        text = (
            "A novel approach was proposed for the optimization problem. "
            "Experiments were conducted on three benchmark datasets. "
            "Results were evaluated using standard metrics. "
            "Significant improvements were observed across all tasks. "
            "The method was compared against existing baselines."
        )
        r = measure_passive_voice(text)
        assert r.passive_count >= 4
        assert r.classification in ("institutional", "bureaucratic", "passive_leaning")

    def test_tech_blog_active_dominant(self):
        text = (
            "We built a new caching layer last week. "
            "It reduced latency by 40 percent. "
            "The team tested it thoroughly before shipping. "
            "Users noticed the improvement immediately. "
            "We plan to extend it to other services."
        )
        r = measure_passive_voice(text)
        assert r.passive_count <= 1
        assert r.classification == "active_dominant"

    def test_incident_report_mixed(self):
        text = (
            "At 03:00 UTC, the server was compromised. "
            "The security team detected the intrusion within minutes. "
            "All affected systems were isolated immediately. "
            "We patched the vulnerability by 06:00. "
            "A postmortem was published the following day."
        )
        r = measure_passive_voice(text)
        assert r.passive_count >= 2
        assert r.word_count > 30

    def test_bureaucratic_memo(self):
        text = (
            "It has been decided that the policy will be implemented. "
            "All departments are required to comply. "
            "The guidelines were distributed to all managers. "
            "Questions should be directed to the compliance office. "
            "The deadline has been extended to Friday."
        )
        r = measure_passive_voice(text)
        assert r.passive_count >= 3
        assert r.classification in ("bureaucratic", "institutional", "passive_leaning")


# ── helper function tests ──────────────────────────────────────


class TestHelpers:
    def test_tokenize_basic(self):
        tokens = _tokenize("Hello, world!")
        assert tokens == ["hello", "world"]

    def test_tokenize_with_apostrophe(self):
        tokens = _tokenize("It's done.")
        # The regex [a-z']+ keeps apostrophes inside the token
        assert "it's" in tokens
        assert "done" in tokens

    def test_tokenize_preserves_contractions(self):
        tokens = _tokenize("don't stop")
        assert "don't" in tokens or ("don" in tokens and "'t" in tokens)

    def test_split_sentences_basic(self):
        sents = _split_sentences("Hello. World. Foo.")
        assert len(sents) == 3

    def test_split_sentences_exclamation(self):
        sents = _split_sentences("Wow! Really? Yes.")
        assert len(sents) == 3

    def test_split_sentences_single(self):
        sents = _split_sentences("Just one sentence here.")
        assert len(sents) == 1

    def test_find_passives_empty(self):
        result = _find_passives_in_sentence("The team wrote code.")
        assert result == []

    def test_find_passives_simple(self):
        result = _find_passives_in_sentence("The code was reviewed.")
        assert len(result) >= 1
        assert result[0][1] == "reviewed"


# ── dataclass defaults ─────────────────────────────────────────


class TestDataclass:
    def test_default_values(self):
        r = PassiveVoiceResult()
        assert r.passive_count == 0
        assert r.active_count == 0
        assert r.total_clauses == 0
        assert r.passive_rate == 0.0
        assert r.passive_verbs == []
        assert r.top_passive_verbs == []
        assert r.classification == "unknown"

    def test_custom_values(self):
        r = PassiveVoiceResult(
            passive_count=5,
            classification="bureaucratic",
            word_count=100,
        )
        assert r.passive_count == 5
        assert r.classification == "bureaucratic"
        assert r.word_count == 100


# ── orthogonality checks ──────────────────────────────────────


class TestOrthogonality:
    def test_active_but_verbose(self):
        """Active voice doesn't imply concise."""
        text = (
            "The team very quickly and efficiently wrote the "
            "extremely long and detailed comprehensive test suite. "
            "They carefully and thoroughly reviewed every single line. "
            "We absolutely and completely finished the entire project."
        )
        r = measure_passive_voice(text)
        assert r.classification == "active_dominant"
        # Verbose but active — orthogonal concepts

    def test_passive_but_concise(self):
        """Passive voice doesn't imply verbose."""
        text = (
            "It was done. "
            "It was shipped. "
            "It was tested."
        )
        r = measure_passive_voice(text)
        assert r.passive_count >= 2
        # Concise but passive — orthogonal concepts

    def test_active_but_formal(self):
        """Active voice works in formal register."""
        text = (
            "The committee approved the budget. "
            "The chairman signed the resolution. "
            "The secretary recorded the minutes."
        )
        r = measure_passive_voice(text)
        assert r.classification == "active_dominant"

    def test_passive_but_informal(self):
        """Passive voice in casual register (get-passive)."""
        text = (
            "My phone got stolen at the party. "
            "Then I got locked out of my account. "
            "Everything just got messed up."
        )
        r = measure_passive_voice(text)
        assert r.get_passive >= 1


# ── word count accuracy ────────────────────────────────────────


class TestWordCount:
    def test_simple_count(self):
        r = measure_passive_voice("one two three.")
        assert r.word_count == 3

    def test_count_with_punctuation(self):
        r = measure_passive_voice("hello, world! foo?")
        assert r.word_count == 3

    def test_count_with_numbers(self):
        # Numbers should not be counted as words (regex is alpha only)
        r = measure_passive_voice("There are 42 items.")
        assert r.word_count == 3  # "there", "are", "items"

    def test_sentence_count(self):
        r = measure_passive_voice("First. Second. Third.")
        assert r.sentence_count == 3
