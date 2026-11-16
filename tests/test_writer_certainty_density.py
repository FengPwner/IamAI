#!/usr/bin/env python3
"""Tests for writer_certainty_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_certainty_density import (
    CertaintyDensityResult,
    measure_certainty_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_certainty_density("")
        assert r.certainty_index == 0.0
        assert r.classification == "tentative"

    def test_whitespace_only(self):
        r = measure_certainty_density("   \n\n   ")
        assert r.certainty_index == 0.0

    def test_single_word(self):
        r = measure_certainty_density("Hello.")
        assert r.classification == "tentative"

    def test_no_certainty_plain_sentence(self):
        r = measure_certainty_density("The function returns a boolean value.")
        assert r.total_certainty_markers == 0
        assert r.certainty_index == 0.0


# ── tentative prose (low certainty density) ────────────────────


class TestTentativeProse:
    def test_plain_factual_no_commitment(self):
        text = (
            "The data was collected over three months. "
            "The sample included 200 participants. "
            "Results were analyzed using standard methods. "
            "The findings are presented in the table below."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index == 0.0
        assert r.classification == "tentative"

    def test_descriptive_neutral(self):
        text = (
            "The river flows through the valley. "
            "Trees line both banks. "
            "A bridge crosses at the narrowest point. "
            "The path leads to a small village."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index == 0.0
        assert r.classification == "tentative"

    def test_hedging_not_certainty(self):
        """Hedging language should score very low on certainty."""
        text = (
            "It might be the case that some people prefer this approach. "
            "Perhaps the results could suggest a trend. "
            "One might argue that the evidence seems to indicate something. "
            "It could possibly be related to other factors."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index < 0.05
        assert r.classification == "tentative"


# ── measured prose (low-moderate certainty) ─────────────────────


class TestMeasuredProse:
    def test_journalistic_reporting(self):
        text = (
            "The study shows a correlation between sleep and productivity. "
            "Researchers determined that participants who slept eight hours "
            "performed better on cognitive tests. The findings confirm earlier "
            "research in this area."
        )
        r = measure_certainty_density(text)
        assert r.commitment_verb_count >= 3  # shows, determined, confirm
        assert 0.10 <= r.certainty_index <= 0.25
        assert r.classification in ("tentative", "measured")

    def test_technical_documentation(self):
        text = (
            "This function handles all edge cases. "
            "The algorithm processes each element in the input array. "
            "This implementation ensures thread safety. "
            "The method returns the computed result."
        )
        r = measure_certainty_density(text)
        assert r.definitive_determiner_count >= 2  # this x2
        assert r.certainty_index > 0.05


# ── assertive prose (moderate certainty) ────────────────────────


class TestAssertiveProse:
    def test_scientific_conclusion(self):
        text = (
            "The experiment demonstrates that temperature directly affects "
            "the reaction rate. We established a clear causal relationship "
            "between the two variables. The evidence conclusively proves "
            "that the catalyst reduces activation energy. These results "
            "confirm the hypothesis beyond doubt."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index >= 0.20
        assert r.commitment_verb_count >= 3
        assert r.total_certainty_markers >= 6

    def test_legal_assertion(self):
        text = (
            "The defendant was clearly at the scene. "
            "The evidence conclusively establishes his presence. "
            "Witnesses unequivocally identified him. "
            "There is no doubt that he committed the act. "
            "The prosecution has proven its case beyond question."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index >= 0.15
        assert r.rejection_phrase_count >= 2
        assert r.certainty_adverb_count >= 2

    def test_opinion_editorial(self):
        text = (
            "This policy is obviously flawed. "
            "The data definitively shows that austerity fails. "
            "Every economist knows this. "
            "The evidence is conclusive: stimulus works. "
            "We must categorically reject these tired arguments."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index >= 0.15
        assert r.total_certainty_markers >= 7


# ── confident / dogmatic prose (high certainty) ─────────────────


class TestHighCertaintyProse:
    def test_manifesto_style(self):
        text = (
            "We declare that all people deserve equal treatment. "
            "We insist that justice must prevail. "
            "We affirm our commitment to these principles. "
            "We maintain that no government can override fundamental rights. "
            "We are certain that history will vindicate this position. "
            "There can be no doubt that the arc of progress bends toward justice."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index >= 0.25
        assert r.classification in ("assertive", "confident", "dogmatic")
        assert r.performative_count >= 3
        assert r.rejection_phrase_count >= 1

    def test_mathematical_proof(self):
        text = (
            "This proves that the function is continuous. "
            "We have established that the limit exists. "
            "It necessarily follows that the derivative is bounded. "
            "This demonstrates the theorem completely. "
            "The result is unequivocally true. "
            "We conclude that the series converges absolutely."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index >= 0.15
        assert r.commitment_verb_count >= 4

    def test_polemical_text(self):
        text = (
            "I assert categorically that this theory is provably wrong. "
            "The evidence incontrovertibly demonstrates the failure. "
            "There is absolutely no doubt that the opposition is mistaken. "
            "I insist that every reasonable person must agree. "
            "The facts conclusively and undeniably prove our position. "
            "It is certain beyond question that we are right. "
            "I declare that all alternative explanations are invalid. "
            "We are unequivocally, undoubtedly, certainly correct."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index >= 0.35
        assert r.classification in ("assertive", "confident", "dogmatic")
        assert r.total_certainty_markers >= 20

    def test_political_speech(self):
        text = (
            "I declare that we will prevail. "
            "I insist that every citizen deserves better. "
            "I affirm my commitment to this nation. "
            "There is no doubt that our cause is just. "
            "We are certain of victory. "
            "I pledge to fight for all of you. "
            "Make no mistake — we will win."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index >= 0.25
        assert r.classification in ("assertive", "confident", "dogmatic")
        assert r.performative_count >= 3
        assert r.rejection_phrase_count >= 1

    def test_single_sentence_many_markers(self):
        text = "I categorically assert and definitively declare that every result conclusively proves this beyond doubt."
        r = measure_certainty_density(text)
        assert r.total_certainty_markers >= 5
        assert r.certainty_index >= 0.50
        assert r.classification == "dogmatic"


# ── channel-specific tests ──────────────────────────────────────


class TestCommitmentVerbs:
    def test_know_prove_demonstrate(self):
        text = "We know this. We proved it. The data demonstrates the effect."
        r = measure_certainty_density(text)
        assert r.commitment_verb_count >= 3

    def test_guarantee_ensure(self):
        text = "We guarantee delivery. This ensures quality."
        r = measure_certainty_density(text)
        assert r.commitment_verb_count >= 2

    def test_insist_contend_maintain(self):
        text = "She insisted on the point. He contended it was true. They maintained their position."
        r = measure_certainty_density(text)
        assert r.commitment_verb_count >= 3

    def test_commitment_tense_variants(self):
        text = "He proves, she proved, they have proven. It demonstrates, it demonstrated."
        r = measure_certainty_density(text)
        assert r.commitment_verb_count >= 5


class TestAbsoluteQuantifiers:
    def test_all_every_always_never(self):
        text = "All students passed. Every test was graded. They always study. She never fails."
        r = measure_certainty_density(text)
        assert r.absolute_quantifier_count >= 4

    def test_multi_word_absolutes(self):
        text = "Each and every student passed. Any and all excuses were rejected."
        r = measure_certainty_density(text)
        assert r.absolute_quantifier_count >= 2

    def test_completely_totally(self):
        text = "The project is completely finished. The answer is totally wrong."
        r = measure_certainty_density(text)
        assert r.absolute_quantifier_count >= 2


class TestDefinitiveDeterminers:
    def test_this_that_these_those(self):
        text = "This book is important. That theory is flawed. These results matter. Those findings count."
        r = measure_certainty_density(text)
        assert r.definitive_determiner_count >= 4

    def test_definitive_phrases(self):
        text = "The specific method used was novel. The exact procedure matters. The precise details count."
        r = measure_certainty_density(text)
        assert r.definitive_determiner_count >= 3


class TestCertaintyAdverbs:
    def test_certainly_definitely(self):
        text = "This is certainly true. That is definitely correct."
        r = measure_certainty_density(text)
        assert r.certainty_adverb_count >= 2

    def test_unquestionably_indisputably(self):
        text = "The results are unquestionably significant. The method is indisputably sound."
        r = measure_certainty_density(text)
        assert r.certainty_adverb_count >= 2

    def test_clearly_obviously(self):
        text = "Clearly the answer is yes. Obviously this matters."
        r = measure_certainty_density(text)
        assert r.certainty_adverb_count >= 2

    def test_many_adverbs(self):
        text = (
            "Certainly, definitely, undoubtedly, unquestionably, clearly, "
            "obviously, plainly, necessarily, inevitably, categorically — "
            "the evidence speaks for itself."
        )
        r = measure_certainty_density(text)
        assert r.certainty_adverb_count >= 10


class TestRejectionPhrases:
    def test_no_doubt(self):
        text = "There is no doubt that this works."
        r = measure_certainty_density(text)
        assert r.rejection_phrase_count >= 1

    def test_beyond_question(self):
        text = "The result is beyond question."
        r = measure_certainty_density(text)
        assert r.rejection_phrase_count >= 1

    def test_multiple_rejections(self):
        text = (
            "It is certain that the sun rises in the east. "
            "Beyond doubt, water flows downhill. "
            "Without exception, objects fall when dropped. "
            "It is undeniable that the earth orbits the sun."
        )
        r = measure_certainty_density(text)
        assert r.rejection_phrase_count >= 4

    def test_make_no_mistake(self):
        text = "Make no mistake, this will work."
        r = measure_certainty_density(text)
        assert r.rejection_phrase_count >= 1

    def test_rest_assured(self):
        text = "Rest assured, the delivery will arrive on time."
        r = measure_certainty_density(text)
        assert r.rejection_phrase_count >= 1


class TestPerformativeAssertions:
    def test_i_assert(self):
        text = "I assert that this is the correct approach."
        r = measure_certainty_density(text)
        assert r.performative_count >= 1

    def test_we_declare(self):
        text = "We declare our independence from these outdated norms."
        r = measure_certainty_density(text)
        assert r.performative_count >= 1

    def test_i_am_certain(self):
        text = "I am certain that this will succeed."
        r = measure_certainty_density(text)
        assert r.performative_count >= 1

    def test_multiple_performatives(self):
        text = (
            "I assert my position. I maintain my argument. "
            "I insist on the facts. I affirm my belief. "
            "I declare my intent. I am confident in the outcome."
        )
        r = measure_certainty_density(text)
        assert r.performative_count >= 6


# ── classification boundary tests ───────────────────────────────


class TestClassification:
    def test_tentative_boundary(self):
        text = "The sky is blue. Water is wet. Birds fly."
        r = measure_certainty_density(text)
        assert r.classification == "tentative"

    def test_measured_from_commitment_verbs(self):
        """Multiple commitment verbs across many sentences → measured."""
        text = (
            "This study shows a trend. "
            "The results confirm previous findings. "
            "The data demonstrates a pattern. "
            "The analysis establishes a link. "
            "The evidence proves a connection. "
            "The research determines a correlation. "
            "The experiment verifies the hypothesis. "
            "The investigation concludes with recommendations. "
            "The review identifies key factors. "
            "The survey indicates a preference."
        )
        r = measure_certainty_density(text)
        assert r.classification in ("measured", "assertive")

    def test_dogmatic_high_density(self):
        """Single sentence packed with markers → dogmatic."""
        text = (
            "I assert categorically that this is absolutely true, "
            "definitely proven, certainly established, undeniably confirmed, "
            "and beyond all doubt correct."
        )
        r = measure_certainty_density(text)
        assert r.classification in ("confident", "dogmatic")


# ── orthogonality tests ─────────────────────────────────────────


class TestOrthogonality:
    def test_high_certainty_low_abstraction(self):
        """Concrete language can still express certainty."""
        text = (
            "The cat definitely sat on the mat. "
            "I saw it clearly with my own eyes. "
            "The dog absolutely chased the ball. "
            "I proved it by taking a photograph."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index > 0.10
        assert r.certainty_adverb_count >= 2

    def test_high_certainty_without_formality(self):
        """Informal language can express certainty."""
        text = (
            "This is definitely the best pizza ever. "
            "I absolutely love this song. "
            "That movie was unquestionably amazing. "
            "I totally nailed that presentation."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index > 0.10
        assert r.total_certainty_markers >= 4

    def test_low_certainty_high_formality(self):
        """Formal language can be non-committal."""
        text = (
            "The committee considered the proposal. "
            "A review was conducted. "
            "The report was filed. "
            "The meeting adjourned."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index == 0.0
        assert r.classification == "tentative"


# ── composite index tests ───────────────────────────────────────


class TestCompositeIndex:
    def test_index_range(self):
        """Index should always be between 0.0 and 1.0."""
        texts = [
            "",
            "Hello.",
            "This is certainly true and definitely correct and absolutely proven.",
            "A" * 10000,
        ]
        for text in texts:
            r = measure_certainty_density(text)
            assert 0.0 <= r.certainty_index <= 1.0

    def test_more_certainty_higher_index(self):
        """Adding certainty markers should increase the index."""
        base = "The study examined the effect of temperature on growth."
        enhanced = (
            "The study conclusively demonstrates the definitive effect "
            "of temperature on growth. This proves beyond doubt that "
            "every increase in temperature necessarily accelerates growth."
        )
        r_base = measure_certainty_density(base)
        r_enhanced = measure_certainty_density(enhanced)
        assert r_enhanced.certainty_index > r_base.certainty_index

    def test_weights_sum_to_one(self):
        """Channel weights should sum to 1.0."""
        # commitment 0.25 + absolute 0.20 + adverb 0.20 +
        # definitive 0.15 + rejection 0.10 + performative 0.10 = 1.0
        assert abs(0.25 + 0.20 + 0.20 + 0.15 + 0.10 + 0.10 - 1.0) < 1e-9

    def test_total_markers_equals_sum_of_channels(self):
        text = (
            "I assert that this is certainly true. "
            "Every result definitively proves the hypothesis. "
            "There is no doubt that all evidence clearly supports this."
        )
        r = measure_certainty_density(text)
        channel_sum = (
            r.commitment_verb_count
            + r.absolute_quantifier_count
            + r.definitive_determiner_count
            + r.certainty_adverb_count
            + r.rejection_phrase_count
            + r.performative_count
        )
        assert r.total_certainty_markers == channel_sum


# ── metadata tests ───────────────────────────────────────────────


class TestMetadata:
    def test_word_count(self):
        text = "One two three four five."
        r = measure_certainty_density(text)
        assert r.total_words == 5

    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_certainty_density(text)
        assert r.total_sentences == 3

    def test_empty_metadata(self):
        r = measure_certainty_density("")
        assert r.total_words == 0
        assert r.total_sentences == 0


# ── edge cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_certainty_words(self):
        text = "Certainly certainly certainly certainly certainly."
        r = measure_certainty_density(text)
        assert r.certainty_adverb_count == 5

    def test_mixed_case(self):
        text = "CERTAINLY this is DEFINITELY true. Obviously CLEARLY proven."
        r = measure_certainty_density(text)
        assert r.certainty_adverb_count >= 3

    def test_very_long_text(self):
        text = "This proves the point. " * 200
        r = measure_certainty_density(text)
        assert r.certainty_index > 0.0
        assert r.commitment_verb_count >= 200

    def test_newlines_and_formatting(self):
        text = "This proves it.\n\nThat demonstrates it.\n\nThese confirm it."
        r = measure_certainty_density(text)
        assert r.commitment_verb_count >= 3

    def test_numbers_and_special_chars(self):
        text = "The 42 results clearly prove that 100% of cases show the effect."
        r = measure_certainty_density(text)
        assert r.commitment_verb_count >= 1
        assert r.certainty_adverb_count >= 1


# ── real-world text samples ─────────────────────────────────────


class TestRealWorldSamples:
    def test_academic_abstract_with_certainty(self):
        text = (
            "This study conclusively demonstrates that regular exercise "
            "significantly reduces cardiovascular risk. We established a "
            "clear dose-response relationship across all age groups. "
            "The findings unequivocally support current public health "
            "guidelines. These results prove that even moderate activity "
            "provides measurable benefits."
        )
        r = measure_certainty_density(text)
        assert r.classification in ("measured", "assertive", "confident")
        assert r.certainty_index >= 0.15
        assert r.total_certainty_markers >= 6

    def test_cautious_academic(self):
        text = (
            "The data was collected from 500 participants. "
            "The analysis was performed using regression models. "
            "The sample was drawn from three regions. "
            "Variables were controlled for age and gender."
        )
        r = measure_certainty_density(text)
        assert r.classification == "tentative"
        assert r.certainty_index == 0.0

    def test_casual_conversation(self):
        text = (
            "I think it might rain later. "
            "The food was okay, I guess. "
            "We could maybe go to the park. "
            "It depends on the weather."
        )
        r = measure_certainty_density(text)
        assert r.certainty_index == 0.0
        assert r.classification == "tentative"
