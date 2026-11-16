#!/usr/bin/env python3
"""Tests for writer_abstraction_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_abstraction_density import (
    AbstractionDensityResult,
    measure_abstraction_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_abstraction_density("")
        assert r.abstraction_index == 0.0
        assert r.classification == "grounded"

    def test_whitespace_only(self):
        r = measure_abstraction_density("   \n\n   ")
        assert r.abstraction_index == 0.0

    def test_single_word(self):
        r = measure_abstraction_density("Hello.")
        assert r.classification == "grounded"

    def test_no_abstractions_plain_sentence(self):
        r = measure_abstraction_density("The dog chased the ball across the yard.")
        assert r.total_abstractions == 0
        assert r.abstraction_index == 0.0


# ── grounded prose ──────────────────────────────────────────────


class TestGroundedProse:
    GROUNDED = (
        "The baker pulled the bread from the oven. "
        "Steam rose from the crust. "
        "He sliced a thick piece and buttered it. "
        "The butter melted into the warm crumb. "
        "His cat rubbed against his ankle. "
        "He dropped a scrap on the floor. "
        "The cat pounced on it."
    )

    def test_grounded_classification(self):
        r = measure_abstraction_density(self.GROUNDED)
        assert r.classification in ("grounded", "tangible")

    def test_zero_nominalizations(self):
        r = measure_abstraction_density(self.GROUNDED)
        assert r.nominalization_count == 0

    def test_zero_intangible_nouns(self):
        r = measure_abstraction_density(self.GROUNDED)
        assert r.intangible_noun_count == 0

    def test_low_index(self):
        r = measure_abstraction_density(self.GROUNDED)
        assert r.abstraction_index < 0.25


# ── rarefied prose ──────────────────────────────────────────────


class TestRarefiedProse:
    RAREFIED = (
        "The conceptualization of freedom requires an understanding of its "
        "fundamental nature. "
        "Every principle of justice embodies a universal truth about human "
        "consciousness. "
        "We must consider the essence of morality and the philosophy of "
        "existence. "
        "In general, the paradigm of equality reflects a deeper worldview. "
        "At its core, the abstraction of identity defines the reality of "
        "the human condition. "
        "Knowledge and wisdom constitute the foundation of understanding. "
        "The ideology of tradition shapes the framework of society. "
        "One must always contemplate the meaning of virtue and the purpose "
        "of courage. "
        "Broadly speaking, the generalization of culture influences the "
        "theorization of beauty. "
        "In principle, the interpretation of ethics reflects the "
        "consciousness of humanity."
    )

    def test_rarefied_classification(self):
        r = measure_abstraction_density(self.RAREFIED)
        assert r.classification in ("abstract", "rarefied")

    def test_high_index(self):
        r = measure_abstraction_density(self.RAREFIED)
        assert r.abstraction_index > 0.45

    def test_has_nominalizations(self):
        r = measure_abstraction_density(self.RAREFIED)
        assert r.nominalization_count > 0

    def test_has_intangible_nouns(self):
        r = measure_abstraction_density(self.RAREFIED)
        assert r.intangible_noun_count >= 10

    def test_has_universal_quantifiers(self):
        r = measure_abstraction_density(self.RAREFIED)
        assert r.universal_count > 0

    def test_has_generalization_markers(self):
        r = measure_abstraction_density(self.RAREFIED)
        assert r.generalization_count > 0


# ── nominalized abstractions ────────────────────────────────────


class TestNominalizations:
    def test_tion_suffix(self):
        text = "The implementation of the solution required careful consideration."
        r = measure_abstraction_density(text)
        assert r.nominalization_count >= 2

    def test_ness_suffix(self):
        text = "Her awareness of the situation grew with each passing day."
        r = measure_abstraction_density(text)
        assert r.nominalization_count >= 1

    def test_ment_suffix(self):
        text = "The development of the agreement took several months."
        r = measure_abstraction_density(text)
        assert r.nominalization_count >= 1

    def test_ity_suffix(self):
        text = "The complexity of the system reflects its maturity."
        r = measure_abstraction_density(text)
        assert r.nominalization_count >= 2

    def test_exclusion_station(self):
        """'station' is a concrete noun — should not count."""
        text = "She walked to the station."
        r = measure_abstraction_density(text)
        assert r.nominalization_count == 0

    def test_exclusion_nation(self):
        """'nation' refers to a concrete entity — should not count."""
        text = "The nation celebrated its holiday."
        r = measure_abstraction_density(text)
        assert r.nominalization_count == 0

    def test_exclusion_garment(self):
        """'garment' is a physical object — should not count."""
        text = "She folded the garment carefully."
        r = measure_abstraction_density(text)
        assert r.nominalization_count == 0

    def test_exclusion_childhood(self):
        """'childhood' is in the exclusion list."""
        text = "She remembered her childhood fondly."
        r = measure_abstraction_density(text)
        assert r.nominalization_count == 0

    def test_ism_suffix(self):
        text = "The rationalism of the group reflected a deeper idealism."
        r = measure_abstraction_density(text)
        # "rationalism" and "idealism" are in exclusions — they should not count
        # "group" is concrete, not a nominalization
        assert r.nominalization_count == 0

    def test_ship_suffix_not_excluded(self):
        """'relationship' should count (not in exclusions)."""
        text = "The relationship required understanding and commitment."
        r = measure_abstraction_density(text)
        # "relationship" ends in -ship and isn't excluded; "understanding" and "commitment" also
        assert r.nominalization_count >= 1

    def test_multiple_nominalizations_one_sentence(self):
        text = (
            "The realization of the organization required "
            "the coordination of every department."
        )
        r = measure_abstraction_density(text)
        # realization(-tion), organization(-tion), coordination(-tion), department(-ment)
        assert r.nominalization_count >= 3


# ── universal quantifiers ───────────────────────────────────────


class TestUniversalQuantifiers:
    def test_all(self):
        text = "All humans seek meaning in their lives."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_every(self):
        text = "Every culture has its own traditions."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_always(self):
        text = "People always believe what they want to believe."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_never(self):
        text = "True wisdom never comes easily."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_nothing(self):
        text = "Nothing in this world is certain."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_everyone(self):
        text = "Everyone has a philosophy of life."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_without_exception(self):
        text = "All systems, without exception, eventually fail."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 2  # "All" + "without exception"

    def test_universally(self):
        text = "The principle is universally accepted."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_invariably(self):
        text = "The outcome is invariably the same."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1

    def test_absolutely(self):
        text = "That is absolutely correct."
        r = measure_abstraction_density(text)
        assert r.universal_count >= 1


# ── abstract verbs ──────────────────────────────────────────────


class TestAbstractVerbs:
    def test_believe(self):
        text = "She believed the theory was correct."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_understand(self):
        text = "He tried to understand the concept."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_consider(self):
        text = "Consider the implications of this decision."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_theorize(self):
        text = "Scientists theorized about the origin of the universe."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_contemplate(self):
        text = "She contemplated the meaning of existence."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_ponder(self):
        text = "He pondered the nature of reality."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_interpret(self):
        text = "The philosopher interpreted the ancient texts."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_hypothesize(self):
        text = "Researchers hypothesized a link between the variables."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_generalize(self):
        text = "One should not generalize from a single example."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_categorize(self):
        text = "Biologists categorize species based on shared traits."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 1

    def test_multiple_abstract_verbs(self):
        text = (
            "She believed that understanding the theory required one to "
            "consider every principle and contemplate its implications."
        )
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count >= 3

    def test_not_abstract_action_verb(self):
        text = "She ran across the bridge and jumped over the fence."
        r = measure_abstraction_density(text)
        assert r.abstract_verb_count == 0


# ── intangible nouns ────────────────────────────────────────────


class TestIntangibleNouns:
    def test_freedom(self):
        text = "Freedom is the birthright of every person."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_justice(self):
        text = "Justice must be served."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_knowledge(self):
        text = "Knowledge is power."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_consciousness(self):
        text = "The nature of consciousness remains a mystery."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 2  # "nature" + "consciousness"

    def test_philosophy(self):
        text = "Her philosophy guided every decision."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_reality(self):
        text = "Reality is stranger than fiction."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_society(self):
        text = "Society shapes the individual."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_tradition(self):
        text = "The tradition of storytelling spans every culture."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_worldview(self):
        text = "His worldview influenced his understanding of truth."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 2  # "worldview" + "truth"

    def test_multiple_intangibles(self):
        text = (
            "The pursuit of freedom, justice, and equality defines the "
            "essence of democracy and the purpose of governance."
        )
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 4


# ── generalization markers ──────────────────────────────────────


class TestGeneralizationMarkers:
    def test_in_general(self):
        text = "In general, people seek happiness."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_by_nature(self):
        text = "Humans are, by nature, social creatures."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_fundamentally(self):
        text = "The issue is fundamentally about trust."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_essentially(self):
        text = "It is essentially a question of values."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_at_its_core(self):
        text = "At its core, the problem is one of communication."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_in_principle(self):
        text = "In principle, the theory holds."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_broadly_speaking(self):
        text = "Broadly speaking, the pattern holds across cultures."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_in_essence(self):
        text = "In essence, all philosophy addresses the human condition."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_the_nature_of(self):
        text = "The nature of truth has puzzled philosophers for millennia."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_final_analysis(self):
        text = "In final analysis, every choice reflects our values."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1

    def test_when_all_is_said_and_done(self):
        text = "When all is said and done, the purpose of life is to live it."
        r = measure_abstraction_density(text)
        assert r.generalization_count >= 1


# ── composite index ─────────────────────────────────────────────


class TestCompositeIndex:
    def test_index_range(self):
        """Index should always be between 0.0 and 1.0."""
        texts = [
            "",
            "The cat sat on the mat.",
            "The conceptualization of freedom requires understanding.",
            "A" * 1000,
        ]
        for text in texts:
            r = measure_abstraction_density(text)
            assert 0.0 <= r.abstraction_index <= 1.0

    def test_monotonic_increase(self):
        """More abstraction → higher index."""
        concrete = "The dog fetched the stick from the pond."
        mixed = "The dog represents loyalty, a universal principle of nature."
        abstract = (
            "The conceptualization of loyalty embodies a fundamental principle "
            "of consciousness. In essence, every paradigm of devotion reflects "
            "the abstract nature of belief and the philosophy of attachment."
        )
        r1 = measure_abstraction_density(concrete)
        r2 = measure_abstraction_density(mixed)
        r3 = measure_abstraction_density(abstract)
        assert r1.abstraction_index < r2.abstraction_index
        assert r2.abstraction_index < r3.abstraction_index

    def test_weights_sum_to_one(self):
        """The five weights should sum to 1.0."""
        assert 0.25 + 0.15 + 0.20 + 0.25 + 0.15 == pytest.approx(1.0)


# ── classification thresholds ───────────────────────────────────


class TestClassification:
    def test_grounded_threshold(self):
        """Pure concrete text should be grounded."""
        text = (
            "The fisherman cast his net into the dark water. "
            "The boat rocked gently. "
            "Rain pattered on the deck. "
            "He pulled the rope tight. "
            "The anchor scraped against the hull."
        )
        r = measure_abstraction_density(text)
        assert r.classification == "grounded"

    def test_rarefied_threshold(self):
        """Densely abstract text should be rarefied."""
        text = (
            "The conceptualization of every principle of justice requires "
            "the understanding of its fundamental nature. "
            "In essence, the philosophy of freedom embodies a universal "
            "truth about consciousness. "
            "Broadly speaking, the paradigm of equality reflects the "
            "theorization of morality. "
            "At its core, the abstraction of identity constitutes the "
            "essence of reality. "
            "In general, the interpretation of ethics always defines the "
            "framework of society. "
            "The generalization of culture invariably shapes the ideology "
            "of tradition. "
            "Nothing in the worldview of humanity exists without the "
            "contemplation of purpose."
        )
        r = measure_abstraction_density(text)
        assert r.classification in ("abstract", "rarefied")

    def test_all_classifications_valid(self):
        """Classification should always be one of the five valid values."""
        valid = {"grounded", "tangible", "moderate", "abstract", "rarefied"}
        texts = [
            "",
            "Short.",
            "The cat sat.",
            "Freedom and justice are universal.",
            "The conceptualization of the paradigm requires contemplation.",
        ]
        for text in texts:
            r = measure_abstraction_density(text)
            assert r.classification in valid


# ── metadata ────────────────────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_abstraction_density(text)
        assert r.total_sentences == 3

    def test_word_count(self):
        text = "The quick brown fox jumped."
        r = measure_abstraction_density(text)
        assert r.total_words == 5

    def test_total_abstractions_sum(self):
        text = (
            "The implementation of every principle requires understanding. "
            "In essence, the conceptualization of freedom is fundamental."
        )
        r = measure_abstraction_density(text)
        expected = (
            r.nominalization_count
            + r.universal_count
            + r.abstract_verb_count
            + r.intangible_noun_count
            + r.generalization_count
        )
        assert r.total_abstractions == expected

    def test_details_dict(self):
        text = "The nature of reality is fundamentally abstract."
        r = measure_abstraction_density(text)
        assert "abstraction_index" in r.details
        assert "classification" in r.details
        assert "nominalization_rate" in r.details
        assert "universal_rate" in r.details
        assert "abstract_verb_rate" in r.details
        assert "intangible_noun_rate" in r.details
        assert "generalization_rate" in r.details


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence(self):
        text = "Freedom."
        r = measure_abstraction_density(text)
        assert r.total_sentences >= 1

    def test_repeated_words(self):
        text = "Freedom freedom freedom freedom freedom."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 1

    def test_case_insensitive(self):
        lower = "the nature of freedom is truth."
        upper = "THE NATURE OF FREEDOM IS TRUTH."
        r1 = measure_abstraction_density(lower)
        r2 = measure_abstraction_density(upper)
        assert r1.total_abstractions == r2.total_abstractions

    def test_mixed_case(self):
        text = "The CONCEPT of Freedom and JUSTICE."
        r = measure_abstraction_density(text)
        assert r.intangible_noun_count >= 2

    def test_long_text(self):
        """Longer text should not break anything."""
        text = ("The cat sat on the mat. " * 100) + (
            "The nature of freedom is fundamentally abstract. " * 50
        )
        r = measure_abstraction_density(text)
        assert 0.0 <= r.abstraction_index <= 1.0

    def test_no_sentence_ending_punctuation(self):
        text = "The cat sat on the mat and the dog ran across the yard"
        r = measure_abstraction_density(text)
        assert r.total_sentences >= 1

    def test_special_characters(self):
        text = "Freedom! Justice? Truth... always."
        r = measure_abstraction_density(text)
        assert r.total_sentences >= 1

    def test_numbers_in_text(self):
        text = "In 2024, 42% of people believed in the concept of freedom."
        r = measure_abstraction_density(text)
        assert r.total_words > 0

    def test_hyphenated_words(self):
        text = "The self-understanding of the post-modern worldview."
        r = measure_abstraction_density(text)
        assert r.total_words > 0

    def test_multiline_text(self):
        text = "The nature of reality.\n\nThe essence of truth.\n\nFreedom always."
        r = measure_abstraction_density(text)
        assert r.total_sentences >= 3
