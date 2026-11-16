#!/usr/bin/env python3
"""Tests for writer_concession_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_concession_density import (
    ConcessionDensityResult,
    measure_concession_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_concession_density("")
        assert r.concession_index == 0.0
        assert r.classification == "unilateral"

    def test_whitespace_only(self):
        r = measure_concession_density("   \n\n   ")
        assert r.concession_index == 0.0

    def test_single_word(self):
        r = measure_concession_density("Hello.")
        assert r.classification == "unilateral"

    def test_no_concession_plain_sentence(self):
        r = measure_concession_density("The function returns a boolean value.")
        assert r.total_concession_markers == 0
        assert r.concession_index == 0.0


# ── unilateral prose (no concession) ───────────────────────────


class TestUnilateralProse:
    def test_plain_factual_no_concession(self):
        text = (
            "The data was collected over three months. "
            "The sample included 200 participants. "
            "Results were analyzed using standard methods. "
            "The findings are presented in the table below."
        )
        r = measure_concession_density(text)
        assert r.concession_index == 0.0
        assert r.classification == "unilateral"

    def test_descriptive_neutral(self):
        text = (
            "The river flows through the valley. "
            "Trees line both banks. "
            "A bridge crosses at the narrowest point. "
            "The path leads to a small village."
        )
        r = measure_concession_density(text)
        assert r.concession_index < 0.05

    def test_academic_reference_style(self):
        text = (
            "Smith (2019) examined the relationship between "
            "sleep quality and cognitive performance. "
            "The study employed a within-subjects design. "
            "Participants completed memory tasks across three sessions."
        )
        r = measure_concession_density(text)
        assert r.classification == "unilateral"
        assert r.total_concession_markers == 0

    def test_recipe_instructions_no_concession(self):
        text = (
            "Preheat the oven to 350 degrees. "
            "Mix the flour and sugar in a large bowl. "
            "Add the eggs one at a time. "
            "Bake for 25 to 30 minutes."
        )
        r = measure_concession_density(text)
        assert r.concession_index < 0.05

    def test_direct_imperative(self):
        text = (
            "Install the package using pip. "
            "Import the module in your script. "
            "Call the function with your data. "
            "Check the output for errors."
        )
        r = measure_concession_density(text)
        assert r.total_concession_markers == 0


# ── occasional concession (mild) ────────────────────────────────


class TestOccasionalConcession:
    def test_single_although(self):
        text = (
            "Although the sample was small, the results were "
            "statistically significant. The effect size was "
            "moderate. The confidence interval was narrow."
        )
        r = measure_concession_density(text)
        assert r.conjunction_count >= 1
        assert r.concession_index > 0.0

    def test_admittedly(self):
        text = (
            "Admittedly, the method has limitations. "
            "However, it remains the most practical approach "
            "for this type of analysis."
        )
        r = measure_concession_density(text)
        assert r.adverb_count >= 1
        assert r.concession_index > 0.0

    def test_granted(self):
        r = measure_concession_density(
            "Granted, the initial investment is high. "
            "The long-term returns justify the cost."
        )
        assert r.adverb_count >= 1

    def test_to_be_sure(self):
        r = measure_concession_density(
            "To be sure, the evidence is not conclusive. "
            "The trend is nonetheless suggestive."
        )
        assert r.adverb_count >= 1

    def test_while_clause(self):
        text = (
            "While the algorithm is slower, it uses less memory. "
            "This makes it suitable for embedded systems."
        )
        r = measure_concession_density(text)
        assert r.conjunction_count >= 1

    def test_even_though(self):
        text = (
            "Even though the test passed, the code needs review. "
            "Several edge cases remain uncovered."
        )
        r = measure_concession_density(text)
        assert r.conjunction_count >= 1

    def test_that_said(self):
        text = (
            "The design is elegant. That said, it sacrifices "
            "performance for readability."
        )
        r = measure_concession_density(text)
        assert r.adverb_count >= 1

    def test_in_fairness(self):
        text = (
            "The proposal has merit. In fairness, the budget "
            "constraints are real."
        )
        r = measure_concession_density(text)
        assert r.adverb_count >= 1


# ── balanced concession ──────────────────────────────────────────


class TestBalancedConcession:
    def test_multiple_concessions_in_paragraph(self):
        text = (
            "Although the framework is new, it has already "
            "gained traction. Admittedly, the documentation "
            "needs improvement. The community is active and "
            "responsive. It is true that the learning curve "
            "is steep. Once mastered, productivity increases "
            "significantly."
        )
        r = measure_concession_density(text)
        assert r.total_concession_markers >= 3
        assert 0.05 <= r.concession_index <= 0.50

    def test_academic_balanced(self):
        text = (
            "While the results support the hypothesis, the "
            "effect size is modest. Granted, the sample was "
            "larger than in previous studies. Nevertheless, "
            "the findings should be interpreted cautiously. "
            "It must be acknowledged that alternative "
            "explanations exist."
        )
        r = measure_concession_density(text)
        assert r.classification in ("occasional", "balanced", "deliberative")
        assert r.total_concession_markers >= 3

    def test_editorial_balanced(self):
        text = (
            "The policy has its merits. On the other hand, "
            "the implementation timeline is unrealistic. "
            "Admittedly, the funding allocation is generous. "
            "It is true that the bureaucratic overhead will "
            "slow progress."
        )
        r = measure_concession_density(text)
        assert r.total_concession_markers >= 3

    def test_concessive_phrases(self):
        text = (
            "One might argue that the cost is prohibitive. "
            "However, the long-term savings offset the initial "
            "investment. Some might say the timeline is too "
            "aggressive. The team has a track record of "
            "delivering on schedule."
        )
        r = measure_concession_density(text)
        assert r.phrase_count >= 2

    def test_performative_concession(self):
        text = (
            "I concede that the previous version had bugs. "
            "The current release addresses all reported issues. "
            "I admit the documentation was lacking. "
            "We have now published a comprehensive guide."
        )
        r = measure_concession_density(text)
        assert r.performative_count >= 2


# ── deliberative / dialectical concession (high density) ───────


class TestDeliberativeConcession:
    def test_heavily_concessive_argument(self):
        text = (
            "Although the theory is elegant, it has limitations. "
            "Admittedly, the data is sparse. While it is true "
            "that the model fits well, one must acknowledge the "
            "risk of overfitting. Granted, the cross-validation "
            "results are promising. Even if we accept the "
            "assumptions, the conclusions remain tentative. "
            "I concede the point about sample diversity."
        )
        r = measure_concession_density(text)
        assert r.concession_index >= 0.15
        assert r.total_concession_markers >= 5

    def test_dialectical_prose(self):
        text = (
            "Although the initial results were promising, "
            "replication failed. Admittedly, the methodology "
            "was sound in principle. While it is true that "
            "the controls were adequate, one might argue that "
            "the sample was biased. I grant that the effect "
            "size was meaningful. Even if we accept the "
            "premise, the conclusion does not follow. "
            "It must be acknowledged that the field lacks "
            "consensus. Granted, alternative approaches exist."
        )
        r = measure_concession_density(text)
        assert r.total_concession_markers >= 6
        assert r.concession_index >= 0.20

    def test_clause_structures(self):
        text = (
            "While it is true that the budget is tight, "
            "we can still proceed. Even if we accept the "
            "worst case, the outcome is manageable. "
            "Granted that the timeline is short, the team "
            "is capable. Regardless of whether the market "
            "cooperates, we must act."
        )
        r = measure_concession_density(text)
        assert r.clause_count >= 2


# ── channel-specific tests ──────────────────────────────────────


class TestConjunctionChannel:
    def test_although(self):
        r = measure_concession_density(
            "Although it rained, we went hiking."
        )
        assert r.conjunction_count >= 1

    def test_though(self):
        r = measure_concession_density(
            "Though tired, she finished the race."
        )
        assert r.conjunction_count >= 1

    def test_albeit(self):
        r = measure_concession_density(
            "The result was positive, albeit modest."
        )
        assert r.conjunction_count >= 1

    def test_notwithstanding(self):
        r = measure_concession_density(
            "Notwithstanding the risks, they proceeded."
        )
        assert r.conjunction_count >= 1

    def test_whereas(self):
        r = measure_concession_density(
            "Whereas the first method was slow, the second was fast."
        )
        assert r.conjunction_count >= 1

    def test_despite(self):
        r = measure_concession_density(
            "Despite the challenges, the project succeeded."
        )
        assert r.conjunction_count >= 1

    def test_in_spite_of(self):
        r = measure_concession_density(
            "In spite of the delays, we met the deadline."
        )
        assert r.conjunction_count >= 1


class TestAdverbChannel:
    def test_admittedly(self):
        r = measure_concession_density("Admittedly, I was wrong.")
        assert r.adverb_count >= 1

    def test_certainly(self):
        r = measure_concession_density(
            "Certainly, the approach has merit."
        )
        assert r.adverb_count >= 1

    def test_indeed(self):
        r = measure_concession_density(
            "Indeed, the evidence supports this claim."
        )
        assert r.adverb_count >= 1

    def test_of_course(self):
        r = measure_concession_density(
            "Of course, there are exceptions."
        )
        assert r.adverb_count >= 1

    def test_no_doubt(self):
        r = measure_concession_density(
            "No doubt, the task is difficult."
        )
        assert r.adverb_count >= 1

    def test_even_so(self):
        r = measure_concession_density(
            "The data is limited. Even so, the pattern is clear."
        )
        assert r.adverb_count >= 1

    def test_fair_enough(self):
        r = measure_concession_density(
            "Fair enough, the concern is valid."
        )
        assert r.adverb_count >= 1


class TestPhraseChannel:
    def test_it_is_true_that(self):
        r = measure_concession_density(
            "It is true that the cost is high."
        )
        assert r.phrase_count >= 1

    def test_one_might_argue(self):
        r = measure_concession_density(
            "One might argue that the design is flawed."
        )
        assert r.phrase_count >= 1

    def test_be_that_as_it_may(self):
        r = measure_concession_density(
            "Be that as it may, we proceed."
        )
        assert r.phrase_count >= 1

    def test_on_the_other_hand(self):
        r = measure_concession_density(
            "On the other hand, the alternative is worse."
        )
        assert r.phrase_count >= 1

    def test_it_must_be_acknowledged(self):
        r = measure_concession_density(
            "It must be acknowledged that the risk is real."
        )
        assert r.phrase_count >= 1

    def test_some_might_say(self):
        r = measure_concession_density(
            "Some might say the effort is futile."
        )
        assert r.phrase_count >= 1


class TestPerformativeChannel:
    def test_i_concede(self):
        r = measure_concession_density("I concede the point.")
        assert r.performative_count >= 1

    def test_i_admit(self):
        r = measure_concession_density("I admit I was mistaken.")
        assert r.performative_count >= 1

    def test_i_acknowledge(self):
        r = measure_concession_density(
            "I acknowledge the limitation."
        )
        assert r.performative_count >= 1

    def test_i_grant(self):
        r = measure_concession_density(
            "I grant that the argument is sound."
        )
        assert r.performative_count >= 1

    def test_we_admit(self):
        r = measure_concession_density(
            "We admit the oversight."
        )
        assert r.performative_count >= 1

    def test_one_must_admit(self):
        r = measure_concession_density(
            "One must admit the result is surprising."
        )
        assert r.performative_count >= 1

    def test_i_must_admit(self):
        r = measure_concession_density(
            "I must admit the solution is clever."
        )
        assert r.performative_count >= 1


class TestClauseChannel:
    def test_while_it_is_true(self):
        r = measure_concession_density(
            "While it is true that costs are rising, "
            "revenue is growing faster."
        )
        assert r.clause_count >= 1

    def test_even_if_we_accept(self):
        r = measure_concession_density(
            "Even if we accept the premise, the conclusion "
            "is debatable."
        )
        assert r.clause_count >= 1

    def test_regardless_of_whether(self):
        r = measure_concession_density(
            "Regardless of whether the plan works, we "
            "must try."
        )
        assert r.clause_count >= 1

    def test_granted_that(self):
        r = measure_concession_density(
            "Granted that the method is imperfect, it "
            "remains the best option."
        )
        assert r.clause_count >= 1

    def test_notwithstanding_that(self):
        r = measure_concession_density(
            "Notwithstanding that the data is limited, "
            "the trend is clear."
        )
        assert r.clause_count >= 1


# ── classification tests ────────────────────────────────────────


class TestClassification:
    def test_unilateral(self):
        text = "The sky is blue. The grass is green. Water is wet."
        r = measure_concession_density(text)
        assert r.classification == "unilateral"

    def test_occasional(self):
        text = (
            "Although the weather was poor, the hike was "
            "enjoyable. The trail was well maintained. "
            "The views were spectacular. The guide was "
            "knowledgeable."
        )
        r = measure_concession_density(text)
        assert r.classification in ("unilateral", "occasional")

    def test_balanced(self):
        text = (
            "Although the method is new, it shows promise. "
            "Admittedly, the sample size is small. It is "
            "true that replication is needed. The initial "
            "results are nonetheless encouraging. While the "
            "theory needs refinement, the core idea is sound. "
            "One might argue the approach is premature. "
            "I concede the limitations are real."
        )
        r = measure_concession_density(text)
        assert r.classification in ("occasional", "balanced", "deliberative")

    def test_classification_values(self):
        """Ensure all classification labels are valid."""
        valid = {"unilateral", "occasional", "balanced",
                 "deliberative", "dialectical"}
        for text in [
            "No concession here at all.",
            "Although one point, the rest is clear.",
            "Although x. Admittedly y. While z. Indeed w.",
            "Although a. Admittedly b. While c. Indeed d. "
            "I concede e. While it is true f. Granted that g. "
            "One might argue h. Even if we accept i. I admit j.",
        ]:
            r = measure_concession_density(text)
            assert r.classification in valid


# ── metadata tests ──────────────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        text = "One. Two. Three."
        r = measure_concession_density(text)
        assert r.total_sentences == 3

    def test_word_count(self):
        text = "The quick brown fox jumps."
        r = measure_concession_density(text)
        assert r.total_words == 5

    def test_total_markers_zero_for_plain(self):
        text = "The cat sat on the mat."
        r = measure_concession_density(text)
        assert r.total_concession_markers == 0

    def test_total_markers_sum(self):
        text = (
            "Although it rained, we went out. "
            "Admittedly, the coat was warm."
        )
        r = measure_concession_density(text)
        assert r.total_concession_markers >= 2

    def test_index_range(self):
        """Index must always be in [0, 1]."""
        texts = [
            "No concession.",
            "Although x, y. Admittedly z.",
            "Although a. Though b. While c. Although d. "
            "Though e. While f. Although g. Though h. "
            "While i. Although j. Though k. While l.",
        ]
        for text in texts:
            r = measure_concession_density(text)
            assert 0.0 <= r.concession_index <= 1.0


# ── orthogonality smoke tests ───────────────────────────────────


class TestOrthogonality:
    def test_concession_vs_hedging(self):
        """Hedging text without concession should score low."""
        text = (
            "The results might suggest a possible link. "
            "Perhaps the correlation indicates some relationship. "
            "It could be that the variables are somewhat related."
        )
        r = measure_concession_density(text)
        assert r.concession_index < 0.10

    def test_concession_vs_certainty(self):
        """Certain text can still be concessive."""
        text = (
            "Although the evidence is conclusive, the "
            "interpretation is certain. Admittedly, the data "
            "proves the hypothesis definitively."
        )
        r = measure_concession_density(text)
        assert r.conjunction_count >= 1
        assert r.adverb_count >= 1

    def test_concession_vs_contrast(self):
        """Contrast without concession (no yielding)."""
        text = (
            "The north is cold. The south is warm. "
            "The east is wet. The west is dry."
        )
        r = measure_concession_density(text)
        assert r.concession_index == 0.0


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_concession_single_sentence(self):
        text = "Although tired and admittedly hungry, she continued."
        r = measure_concession_density(text)
        assert r.total_concession_markers >= 2

    def test_case_insensitive(self):
        r1 = measure_concession_density("Although it rained.")
        r2 = measure_concession_density("ALTHOUGH IT RAINED.")
        assert r1.conjunction_count == r2.conjunction_count

    def test_punctuation_handling(self):
        text = "Although, yes, it rained; we still went out."
        r = measure_concession_density(text)
        assert r.conjunction_count >= 1

    def test_very_long_text(self):
        sentences = [
            "Although the method works, it is slow." * 20,
            "Admittedly, the approach has merit." * 10,
            "The data is clean." * 30,
        ]
        text = " ".join(sentences)
        r = measure_concession_density(text)
        assert 0.0 <= r.concession_index <= 1.0
        assert r.total_sentences > 0

    def test_single_sentence_concession(self):
        r = measure_concession_density(
            "Although the night was dark, the stars shone."
        )
        assert r.conjunction_count >= 1
        assert r.total_sentences >= 1

    def test_no_false_positive_on_similar_words(self):
        """Words like 'allow' should not trigger unless in pattern."""
        text = (
            "We allow the process to run. "
            "The allocation is complete. "
            "All participants received materials."
        )
        r = measure_concession_density(text)
        assert r.performative_count == 0
