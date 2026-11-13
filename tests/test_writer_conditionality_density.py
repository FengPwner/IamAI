#!/usr/bin/env python3
"""Tests for writer_conditionality_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_conditionality_density import (
    ConditionalityDensityResult,
    measure_conditionality_density,
)


# ── empty / degenerate input ────────────────────────────────────

class TestEmptyInput:
    def test_empty_string(self):
        r = measure_conditionality_density("")
        assert r.conditionality_density_index == 0.0
        assert r.classification == "unconditional"

    def test_whitespace_only(self):
        r = measure_conditionality_density("   \n\n   ")
        assert r.conditionality_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_conditionality_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1


# ── plain declarative prose (no conditionals) ───────────────────

class TestDeclarativeProse:
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

    def test_unconditional_classification(self):
        r = measure_conditionality_density(self.PLAIN)
        assert r.classification == "unconditional"
        assert r.conditionality_density_index < 0.05

    def test_low_conditional_counts(self):
        r = measure_conditionality_density(self.PLAIN)
        assert r.explicit_conditional_count == 0
        assert r.subjunctive_count == 0
        assert r.hypothetical_marker_count == 0
        assert r.counterfactual_count == 0


# ── explicit conditionals (if/then, unless) ─────────────────────

class TestExplicitConditionals:
    EXPLICIT = (
        "If the temperature drops below zero, the water freezes. "
        "Unless you have a reservation, entry is denied. Provided "
        "that all conditions are met, the contract is valid. In "
        "case of emergency, break the glass. As long as the engine "
        "runs, the alternator charges the battery. If the defendant "
        "fails to appear, the court may issue a warrant. If you "
        "need help, then ask. So long as the agreement holds, both "
        "parties benefit. In the event that negotiations fail, "
        "arbitration is the next step. If need be, we can adjourn "
        "until Monday."
    )

    def test_explicit_classification(self):
        r = measure_conditionality_density(self.EXPLICIT)
        assert r.classification in ("moderately_conditional", "heavily_conditional")
        assert r.explicit_conditional_count >= 8

    def test_explicit_rate_positive(self):
        r = measure_conditionality_density(self.EXPLICIT)
        assert r.explicit_conditional_rate > 0

    def test_explicit_count_reasonable(self):
        r = measure_conditionality_density(self.EXPLICIT)
        # At least the "if" instances: ~7 occurrences of "if"
        assert r.explicit_conditional_count >= 7


# ── subjunctive / counterfactual ────────────────────────────────

class TestSubjunctive:
    SUBJUNCTIVE = (
        "Were it not for the rain, the crops would have withered. "
        "If I were you, I would reconsider the offer. Had she "
        "known the truth, she would have acted differently. Were "
        "he to arrive on time, the meeting could proceed as "
        "planned. Had it not been for the quick response, the "
        "patient might not have survived. As if she were dreaming, "
        "she walked through the fog. Should you wish to appeal, "
        "the deadline is thirty days. Had the bridge held, the "
        "retreat would have been orderly."
    )

    def test_subjunctive_count(self):
        r = measure_conditionality_density(self.SUBJUNCTIVE)
        assert r.subjunctive_count >= 4

    def test_subjunctive_rate_positive(self):
        r = measure_conditionality_density(self.SUBJUNCTIVE)
        assert r.subjunctive_rate > 0


# ── hypothetical markers ────────────────────────────────────────

class TestHypothetical:
    HYPOTHETICAL = (
        "Suppose the universe were infinite. Imagine a world "
        "without gravity. What if the experiment fails? Let us "
        "assume the data is correct. For the sake of argument, "
        "grant that free will exists. Suppose the algorithm "
        "converges. Imagine the consequences of such a policy. "
        "What if we are wrong about the timeline? Let's say the "
        "budget doubles. Postulate a new particle with these "
        "properties. Conceive of a society without money. "
        "Envision a future where energy is free."
    )

    def test_hypothetical_count(self):
        r = measure_conditionality_density(self.HYPOTHETICAL)
        assert r.hypothetical_marker_count >= 9

    def test_hypothetical_classification(self):
        r = measure_conditionality_density(self.HYPOTHETICAL)
        assert r.classification in ("moderately_conditional", "heavily_conditional")

    def test_hypothetical_rate_positive(self):
        r = measure_conditionality_density(self.HYPOTHETICAL)
        assert r.hypothetical_marker_rate > 0


# ── concessive conditionals ─────────────────────────────────────

class TestConcessiveConditional:
    CONCESSIVE = (
        "Even if the plan succeeds, the underlying problem "
        "remains. No matter what happens, we must be prepared. "
        "Even though the evidence suggests otherwise, the theory "
        "might still hold. Whatever happens, stay calm. Even if "
        "you disagree, hear me out. No matter how difficult the "
        "task, we must attempt it. Even if the cost is high, the "
        "investment is necessary. No matter when you arrive, "
        "someone will be here. Come what may, the show goes on."
    )

    def test_concessive_count(self):
        r = measure_conditionality_density(self.CONCESSIVE)
        assert r.concessive_conditional_count >= 6

    def test_concessive_rate_positive(self):
        r = measure_conditionality_density(self.CONCESSIVE)
        assert r.concessive_conditional_rate > 0


# ── contingent consequence ──────────────────────────────────────

class TestContingentConsequence:
    CONSEQUENCE = (
        "The reactor overheated, and consequently the coolant "
        "failed. The contract was breached; accordingly, damages "
        "are owed. If the test fails, then the hypothesis must "
        "be revised. Finish your work; otherwise, you will miss "
        "the deadline. If the vote passes, the policy takes "
        "effect immediately, and in that case the old rules no "
        "longer apply. Submit the form, or else the application "
        "will be voided. The signal was received, and thereupon "
        "the mechanism engaged."
    )

    def test_consequence_count(self):
        r = measure_conditionality_density(self.CONSEQUENCE)
        assert r.contingent_consequence_count >= 4

    def test_consequence_rate_positive(self):
        r = measure_conditionality_density(self.CONSEQUENCE)
        assert r.contingent_consequence_rate > 0


# ── counterfactual ──────────────────────────────────────────────

class TestCounterfactual:
    COUNTERFACTUAL = (
        "If the treaty had been signed, the war might have "
        "ended sooner. Had the captain turned the wheel, the "
        "ship would have avoided the reef. If she had studied "
        "harder, she could have passed the exam. Had the "
        "message arrived on time, the meeting would have been "
        "postponed. If they had invested earlier, they might "
        "have avoided the losses."
    )

    def test_counterfactual_count(self):
        r = measure_conditionality_density(self.COUNTERFACTUAL)
        assert r.counterfactual_count >= 2

    def test_counterfactual_rate_positive(self):
        r = measure_conditionality_density(self.COUNTERFACTUAL)
        assert r.counterfactual_rate > 0


# ── composite properties ────────────────────────────────────────

class TestComposite:
    def test_index_range(self):
        """Index must be in [0, 1]."""
        texts = [
            "The cat sat on the mat.",
            "If the temperature drops, the water freezes. " * 10,
            "Suppose imagine assume postulate envisage envision." * 5,
        ]
        for text in texts:
            r = measure_conditionality_density(text)
            assert 0.0 <= r.conditionality_density_index <= 1.0

    def test_higher_conditionals_higher_index(self):
        """More conditionals should produce a higher index."""
        low = "The cat sat on the mat. The dog ran in the park."
        high = (
            "If the cat sits, then the dog runs. Unless the "
            "park closes, the children play. Suppose the weather "
            "changes, then the event moves indoors. If the plan "
            "fails, otherwise we improvise."
        )
        r_low = measure_conditionality_density(low)
        r_high = measure_conditionality_density(high)
        assert r_high.conditionality_density_index > r_low.conditionality_density_index

    def test_empty_has_zero_index(self):
        r = measure_conditionality_density("")
        assert r.conditionality_density_index == 0.0


# ── classification thresholds ───────────────────────────────────

class TestClassification:
    def test_unconditional(self):
        r = measure_conditionality_density(
            "The sun rose. Birds sang. The river flowed steadily."
        )
        assert r.classification == "unconditional"

    def test_heavily_conditional(self):
        text = (
            "If the experiment succeeds, then the hypothesis is "
            "confirmed. Unless the data is corrupted, the results "
            "stand. Provided that the sample is representative, the "
            "conclusions generalize. If the temperature rises, then "
            "the reaction accelerates. In case of failure, the "
            "backup protocol activates. Suppose the model is correct. "
            "Imagine the implications. If the variables interact, "
            "then the outcome depends on the initial conditions. "
            "As long as the funding continues, the research proceeds."
        )
        r = measure_conditionality_density(text)
        assert r.classification in ("moderately_conditional", "heavily_conditional", "condition_saturated")

    def test_classification_consistency(self):
        """Same text should always get the same classification."""
        text = "If the rain stops, we will go outside."
        r1 = measure_conditionality_density(text)
        r2 = measure_conditionality_density(text)
        assert r1.classification == r2.classification
        assert r1.conditionality_density_index == r2.conditionality_density_index


# ── diversity ───────────────────────────────────────────────────

class TestDiversity:
    def test_diverse_conditionals(self):
        """Text using many different conditional forms."""
        text = (
            "If the plan works, we celebrate. Unless the funding "
            "is cut, the project continues. Suppose the algorithm "
            "converges. Imagine the outcome. Provided that the "
            "data holds. As long as the system is stable. "
            "Whatever happens, we adapt. Even if the worst occurs, "
            "we have backups. In case of emergency, evacuate."
        )
        r = measure_conditionality_density(text)
        assert r.unique_conditional_forms >= 6
        assert r.conditional_diversity_index > 0.2

    def test_single_form_low_diversity(self):
        """Text using only 'if' should have lower diversity."""
        text = "If it rains. If it snows. If it hails. If it floods."
        r = measure_conditionality_density(text)
        assert r.conditional_diversity_index < 0.5


# ── edge cases ──────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_sentence(self):
        r = measure_conditionality_density("If it rains, we stay inside.")
        assert r.total_sentences >= 1
        assert r.explicit_conditional_count >= 1

    def test_very_long_text(self):
        text = "If the system works, then it works. " * 200
        r = measure_conditionality_density(text)
        assert r.conditionality_density_index > 0
        assert r.total_sentences > 100

    def test_conditional_without_then(self):
        """'If it rains we stay' without explicit 'then'."""
        r = measure_conditionality_density("If it rains, we cancel the picnic.")
        assert r.explicit_conditional_count >= 1

    def test_case_insensitive(self):
        """Conditionals should be detected regardless of case."""
        lower = "if it rains, we stay."
        upper = "IF IT RAINS, WE STAY."
        r_lower = measure_conditionality_density(lower)
        r_upper = measure_conditionality_density(upper)
        assert r_lower.explicit_conditional_count == r_upper.explicit_conditional_count


# ── orthogonality ───────────────────────────────────────────────

class TestOrthogonality:
    def test_high_modality_low_conditionality(self):
        """Modality-rich text should not score high on conditionality
        unless it actually contains conditional structures."""
        modal = (
            "You must finish the report. She should call ahead. "
            "They ought to arrive early. He has to submit the form. "
            "Staff shall wear badges. You need to sign in."
        )
        r = measure_conditionality_density(modal)
        assert r.conditionality_density_index < 0.15

    def test_high_causal_low_conditionality(self):
        """Causal-rich text should not score high on conditionality."""
        causal = (
            "The experiment failed because the temperature was too "
            "high. Therefore, the team revised the protocol. As a "
            "result, the next trial succeeded. The data confirms "
            "the hypothesis. Consequently, the paper was accepted."
        )
        r = measure_conditionality_density(causal)
        # "consequently" and "therefore" may trigger consequence patterns
        # but the overall conditionality should be modest
        assert r.explicit_conditional_count == 0

    def test_high_hedging_low_conditionality(self):
        """Hedging-rich text should not score high on conditionality
        unless it uses conditional structures."""
        hedging = (
            "It seems likely that the results are significant. "
            "Perhaps the methodology needs revision. The findings "
            "tend to suggest a correlation. Somewhat surprisingly, "
            "the data aligns with the prediction. To some extent, "
            "the theory holds."
        )
        r = measure_conditionality_density(hedging)
        assert r.explicit_conditional_count == 0
        assert r.conditionality_density_index < 0.20

    def test_high_interrogative_low_conditionality(self):
        """Questions without conditional markers should not inflate score."""
        questions = (
            "What time is the meeting? Who sent the email? "
            "Where did the files go? When does the train arrive? "
            "Why was the decision made? How many attendees confirmed?"
        )
        r = measure_conditionality_density(questions)
        assert r.explicit_conditional_count == 0
        assert r.conditionality_density_index < 0.15


# ── details dict ────────────────────────────────────────────────

class TestDetails:
    def test_details_populated(self):
        r = measure_conditionality_density(
            "If the system is overloaded, then it crashes."
        )
        assert "conditionality_density_index" in r.details
        assert "classification" in r.details
        assert "explicit_conditional_rate" in r.details
        assert "subjunctive_rate" in r.details
        assert "counterfactual_rate" in r.details

    def test_details_match_fields(self):
        r = measure_conditionality_density(
            "Suppose the model works. Then we can predict outcomes."
        )
        assert r.details["conditionality_density_index"] == r.conditionality_density_index
        assert r.details["classification"] == r.classification


# ── sentence counting ───────────────────────────────────────────

class TestSentenceCounting:
    def test_basic_count(self):
        r = measure_conditionality_density("One. Two. Three.")
        assert r.total_sentences == 3

    def test_exclamation_count(self):
        r = measure_conditionality_density("Stop! Wait! Go!")
        assert r.total_sentences == 3

    def test_question_count(self):
        r = measure_conditionality_density("What if? Why not? How so?")
        assert r.total_sentences == 3


# ── rates per 100 sentences ─────────────────────────────────────

class TestRates:
    def test_explicit_rate_calculation(self):
        """10 sentences with 5 explicit conditionals = rate ~50."""
        text = "If this. If that. If here. If there. If now. "
        text += "One. Two. Three. Four. Five."
        r = measure_conditionality_density(text)
        assert r.explicit_conditional_rate > 0

    def test_zero_rate_no_conditionals(self):
        text = "The cat sat. The dog ran. The bird flew."
        r = measure_conditionality_density(text)
        assert r.explicit_conditional_rate == 0.0


# ── real-world prose samples ────────────────────────────────────

class TestRealWorldProse:
    SCIENTIFIC = (
        "The results of the experiment confirmed the hypothesis. "
        "The control group showed no significant change. The "
        "treatment group, however, exhibited a marked improvement. "
        "The researchers concluded that the intervention was "
        "effective. The sample size was adequate for the observed "
        "effect size. The methodology followed established "
        "protocols. The data was analyzed using standard "
        "statistical methods."
    )

    LEGAL = (
        "If the tenant fails to pay rent within five days of the "
        "due date, the landlord may issue a notice to quit. Unless "
        "the tenant cures the default within fourteen days, the "
        "landlord may terminate the lease. Provided that the tenant "
        "has complied with all other terms, the security deposit "
        "shall be returned within thirty days. In case of damage "
        "to the premises, the tenant is liable for repair costs. "
        "If the landlord fails to maintain the premises as required "
        "by law, the tenant may withhold rent."
    )

    def test_scientific_low_conditionality(self):
        r = measure_conditionality_density(self.SCIENTIFIC)
        assert r.classification in ("unconditional", "lightly_conditional")

    def test_legal_high_conditionality(self):
        r = measure_conditionality_density(self.LEGAL)
        assert r.classification in ("moderately_conditional", "heavily_conditional", "condition_saturated")

    def test_legal_higher_than_scientific(self):
        r_sci = measure_conditionality_density(self.SCIENTIFIC)
        r_legal = measure_conditionality_density(self.LEGAL)
        assert r_legal.conditionality_density_index > r_sci.conditionality_density_index
