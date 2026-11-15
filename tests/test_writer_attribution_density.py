#!/usr/bin/env python3
"""Tests for writer_attribution_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_attribution_density import (
    AttributionDensityResult,
    measure_attribution_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_attribution_density("")
        assert r.attribution_density_index == 0.0
        assert r.classification == "unattributed"

    def test_whitespace_only(self):
        r = measure_attribution_density("   \n\n   ")
        assert r.attribution_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_attribution_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1

    def test_single_word(self):
        r = measure_attribution_density("Hello")
        assert r.attribution_density_index == 0.0
        assert r.classification == "unattributed"

    def test_single_sentence_no_attribution(self):
        r = measure_attribution_density("The sky is blue today.")
        assert r.explicit_attribution_count == 0
        assert r.quoted_speech_count == 0


# ── unattributed prose (no source references) ───────────────────


class TestUnattributedProse:
    PLAIN = (
        "The concept of justice involves fairness and equity. "
        "Mathematical proofs require logical deduction from axioms. "
        "Philosophical arguments explore the nature of existence. "
        "Aesthetic appreciation depends on cultural context. "
        "Ethical frameworks guide moral reasoning. "
        "The architecture of the building reflects modernist principles. "
        "Water flows downhill due to gravity. "
        "Music engages both cognitive and emotional processing."
    )

    def test_unattributed_classification(self):
        r = measure_attribution_density(self.PLAIN)
        assert r.classification == "unattributed"
        assert r.attribution_density_index < 0.05

    def test_zero_attribution_counts(self):
        r = measure_attribution_density(self.PLAIN)
        assert r.explicit_attribution_count == 0
        assert r.quoted_speech_count == 0
        assert r.expert_appeal_count == 0
        assert r.consensus_appeal_count == 0
        assert r.weasel_attribution_count == 0
        assert r.reported_speech_count == 0
        assert r.source_pattern_count == 0

    def test_zero_attribution_ratio(self):
        r = measure_attribution_density(self.PLAIN)
        assert r.attribution_sentence_ratio == 0.0

    def test_zero_diversity(self):
        r = measure_attribution_density(self.PLAIN)
        assert r.source_diversity_index == 0.0


# ── explicit attribution ────────────────────────────────────────


class TestExplicitAttribution:
    EXPLICIT = (
        "According to Dr. Smith, the results are significant. "
        "As noted by the research team, the correlation is strong. "
        "According to the latest report, inflation has stabilized. "
        "As Jones argues in his paper, the model needs revision. "
        "In the words of the committee chair, the decision was final. "
        "According to the WHO guidelines, vaccination is essential. "
        "As stated by the spokesperson, negotiations are ongoing. "
        "According to the data from NASA, temperatures are rising. "
        "As observed by the field team, migration patterns shifted. "
        "According to the annual survey, satisfaction improved."
    )

    def test_explicit_heavy_classification(self):
        r = measure_attribution_density(self.EXPLICIT)
        assert r.classification in (
            "heavily_attributed",
            "source_saturated",
        )
        assert r.explicit_attribution_count >= 8

    def test_explicit_rate_high(self):
        r = measure_attribution_density(self.EXPLICIT)
        assert r.explicit_attribution_rate > 60.0

    def test_attribution_ratio_high(self):
        r = measure_attribution_density(self.EXPLICIT)
        assert r.attribution_sentence_ratio > 0.6

    def test_diversity_low(self):
        """Only explicit attribution used, so diversity should be low."""
        r = measure_attribution_density(self.EXPLICIT)
        assert r.source_diversity_index < 0.5


# ── quoted speech ───────────────────────────────────────────────


class TestQuotedSpeech:
    QUOTED = (
        'The mayor said that the budget would be approved by Friday. '
        'She stated the new policy takes effect immediately. '
        'The witness told the committee that he saw everything. '
        'Dr. Lee explained the procedure takes about two hours. '
        'The professor argued that traditional methods are outdated. '
        'The CEO announced the merger would close next quarter. '
        'The defendant claimed he was nowhere near the scene. '
        'The reporter noted the source requested anonymity. '
        'The teacher replied that homework is due Monday. '
        'The scientist confirmed the results were reproducible.'
    )

    def test_quoted_classification(self):
        r = measure_attribution_density(self.QUOTED)
        assert r.classification in (
            "moderately_attributed",
            "heavily_attributed",
        )
        assert r.quoted_speech_count >= 5

    def test_quoted_rate_positive(self):
        r = measure_attribution_density(self.QUOTED)
        assert r.quoted_speech_rate > 30.0


# ── expert appeal ───────────────────────────────────────────────


class TestExpertAppeal:
    EXPERT = (
        "Experts agree that climate change is accelerating. "
        "Researchers found a link between sleep and memory. "
        "Scientists discovered a new species in the deep ocean. "
        "Leading expert in the field, Dr. Sarah Chen of MIT, "
        "published groundbreaking results last year. "
        "The peer-reviewed study confirms the hypothesis. "
        "Researchers suggest that exercise improves cognition. "
        "Scientists warn that biodiversity loss is critical. "
        "Experts say the economy will recover by next year. "
        "A professor at Stanford University led the study."
    )

    def test_expert_classification(self):
        r = measure_attribution_density(self.EXPERT)
        assert r.classification in (
            "moderately_attributed",
            "heavily_attributed",
        )
        assert r.expert_appeal_count >= 5

    def test_expert_rate_positive(self):
        r = measure_attribution_density(self.EXPERT)
        assert r.expert_appeal_rate > 30.0


# ── consensus appeal ────────────────────────────────────────────


class TestConsensusAppeal:
    CONSENSUS = (
        "It is widely accepted that the earth orbits the sun. "
        "There is a growing consensus among economists about inflation. "
        "It is common knowledge that water freezes at zero degrees. "
        "The majority of researchers agree on the methodology. "
        "Most experts believe the treatment is effective. "
        "It is well-known that smoking causes health problems. "
        "Everyone knows that exercise is good for you. "
        "The scientific consensus supports vaccination. "
        "It is generally agreed that education reduces poverty. "
        "Most studies show a positive correlation."
    )

    def test_consensus_classification(self):
        r = measure_attribution_density(self.CONSENSUS)
        assert r.classification in (
            "moderately_attributed",
            "heavily_attributed",
        )
        assert r.consensus_appeal_count >= 5

    def test_consensus_rate_positive(self):
        r = measure_attribution_density(self.CONSENSUS)
        assert r.consensus_appeal_rate > 30.0

    def test_low_traceability(self):
        """Consensus appeals are less traceable."""
        r = measure_attribution_density(self.CONSENSUS)
        assert r.traceability_score < 0.5


# ── weasel attribution ─────────────────────────────────────────


class TestWeaselAttribution:
    WEASEL = (
        "Some people say the policy is ineffective. "
        "It is believed that the economy will improve. "
        "Studies show that meditation reduces stress. "
        "Critics argue the plan is too ambitious. "
        "Some experts suggest alternative approaches exist. "
        "It is said that the company is considering layoffs. "
        "Reports indicate a decline in enrollment. "
        "Many studies confirm the benefits of early education. "
        "Allegedly, the funds were misappropriated. "
        "Several reports document similar incidents."
    )

    def test_weasel_classification(self):
        r = measure_attribution_density(self.WEASEL)
        assert r.classification in (
            "moderately_attributed",
            "heavily_attributed",
        )
        assert r.weasel_attribution_count >= 5

    def test_weasel_rate_positive(self):
        r = measure_attribution_density(self.WEASEL)
        assert r.weasel_attribution_rate > 30.0

    def test_low_traceability(self):
        """Weasel attributions are untraceable by nature."""
        r = measure_attribution_density(self.WEASEL)
        assert r.traceability_score < 0.5


# ── reported speech ────────────────────────────────────────────


class TestReportedSpeech:
    REPORTED = (
        "According to reports, the meeting was productive. "
        "It was reported that the deal closed yesterday. "
        "The data indicates a significant improvement. "
        "Records show the building was constructed in 1920. "
        "According to official sources, the count is accurate. "
        "It has been confirmed that the suspect was arrested. "
        "The documents describe a complex financial scheme. "
        "It was documented in the trial transcript. "
        "According to estimates, the population doubled. "
        "The archives record three separate incidents."
    )

    def test_reported_classification(self):
        r = measure_attribution_density(self.REPORTED)
        assert r.classification in (
            "moderately_attributed",
            "heavily_attributed",
        )

    def test_reported_speech_detected(self):
        r = measure_attribution_density(self.REPORTED)
        assert (
            r.reported_speech_count > 0
            or r.explicit_attribution_count > 0
        )


# ── anonymous source patterns ──────────────────────────────────


class TestAnonymousSources:
    ANONYMOUS = (
        "A senior source close to the matter confirmed the deal. "
        "An anonymous source said the merger is imminent. "
        "Sources familiar with the matter described tensions. "
        "A government official who asked not to be named "
        "revealed the budget shortfall. "
        "Speaking on condition of anonymity, the diplomat "
        "described the negotiations as fragile. "
        "A well-placed source said the decision was made last week. "
        "An industry insider reported declining sales figures. "
        "A confidential source provided the documents. "
        "Sources with direct knowledge of the situation agreed."
    )

    def test_anonymous_source_detected(self):
        r = measure_attribution_density(self.ANONYMOUS)
        assert r.source_pattern_count >= 3

    def test_anonymous_contributes_to_density(self):
        r = measure_attribution_density(self.ANONYMOUS)
        assert r.attribution_density_index > 0.05


# ── mixed attribution (high diversity) ─────────────────────────


class TestMixedAttribution:
    MIXED = (
        "According to Dr. Chen, the vaccine is 95% effective. "
        "The researcher said that side effects were minimal. "
        "Experts agree that the variant is more transmissible. "
        "Studies show a correlation between age and severity. "
        "It is widely accepted that masks reduce transmission. "
        "The WHO reported a decline in global cases. "
        "A senior source close to the trial confirmed results. "
        "As noted by the committee, funding remains inadequate. "
        "Most scientists believe booster shots are necessary. "
        "It was reported that the approval came Friday."
    )

    def test_mixed_high_diversity(self):
        r = measure_attribution_density(self.MIXED)
        assert r.source_diversity_index >= 0.5

    def test_mixed_classification(self):
        r = measure_attribution_density(self.MIXED)
        assert r.classification in (
            "moderately_attributed",
            "heavily_attributed",
            "source_saturated",
        )

    def test_mixed_moderate_traceability(self):
        """Mix of traceable and untraceable sources."""
        r = measure_attribution_density(self.MIXED)
        assert 0.2 < r.traceability_score < 0.9


# ── journalism-style prose (heavy attribution) ────────────────


class TestJournalismProse:
    JOURNALISM = (
        "According to the White House, the bill will create "
        "thousands of jobs. The president stated that the "
        "infrastructure plan is a priority. Senior officials "
        "said negotiations with Congress are ongoing. "
        "Experts warn that the timeline may be optimistic. "
        "The Congressional Budget Office reported the cost "
        "at $2 trillion over ten years. According to sources "
        "familiar with the matter, bipartisan support is "
        "growing. Senator Jones argued that amendments are "
        "needed. The committee chair noted that hearings "
        "will begin next month. It was reported that several "
        "Republican senators expressed concerns."
    )

    def test_journalism_heavily_attributed(self):
        r = measure_attribution_density(self.JOURNALISM)
        assert r.classification in (
            "heavily_attributed",
            "source_saturated",
        )

    def test_journalism_high_ratio(self):
        r = measure_attribution_density(self.JOURNALISM)
        assert r.attribution_sentence_ratio > 0.4

    def test_journalism_multiple_mechanisms(self):
        r = measure_attribution_density(self.JOURNALISM)
        categories_used = sum(
            1
            for c in [
                r.explicit_attribution_count,
                r.quoted_speech_count,
                r.expert_appeal_count,
                r.reported_speech_count,
                r.source_pattern_count,
            ]
            if c > 0
        )
        assert categories_used >= 3


# ── academic prose (moderate-to-heavy attribution) ──────────────


class TestAcademicProse:
    ACADEMIC = (
        "According to Smith et al., the correlation coefficient "
        "was 0.78. The researchers found that the intervention "
        "produced measurable effects. As noted by Johnson in "
        "her 2022 paper, sample size affects statistical power. "
        "The peer-reviewed study published in Nature confirms "
        "the hypothesis. Previous work by Chen and Patel "
        "demonstrated similar results across populations. "
        "The consensus among scholars is that the framework "
        "needs revision. According to the data, the effect "
        "size exceeds the threshold for clinical significance."
    )

    def test_academic_classification(self):
        r = measure_attribution_density(self.ACADEMIC)
        assert r.classification in (
            "moderately_attributed",
            "heavily_attributed",
        )

    def test_academic_explicit_count(self):
        r = measure_attribution_density(self.ACADEMIC)
        assert r.explicit_attribution_count >= 2


# ── fiction / first-person (minimal attribution) ───────────────


class TestFictionProse:
    FICTION = (
        "She walked through the garden, breathing in the "
        "jasmine. The old house stood at the end of the path, "
        "its windows dark. She pushed open the gate and stepped "
        "inside. Dust covered every surface. A photograph on "
        "the mantle caught her eye. She picked it up and "
        "studied the faces. The clock on the wall had stopped "
        "at midnight. She set the photo down and climbed the "
        "stairs. Each step creaked beneath her weight."
    )

    def test_fiction_unattributed(self):
        r = measure_attribution_density(self.FICTION)
        assert r.classification in ("unattributed", "lightly_attributed")
        assert r.attribution_density_index < 0.15

    def test_fiction_no_explicit(self):
        r = measure_attribution_density(self.FICTION)
        assert r.explicit_attribution_count == 0
        assert r.quoted_speech_count == 0
        assert r.expert_appeal_count == 0


# ── short text edge cases ──────────────────────────────────────


class TestShortTexts:
    def test_one_sentence_attributed(self):
        r = measure_attribution_density(
            "According to the report, sales increased 20%."
        )
        assert r.explicit_attribution_count >= 1
        assert r.total_sentences == 1

    def test_two_sentences_one_attributed(self):
        text = (
            "The sky is blue. According to NASA, the ocean "
            "is warming."
        )
        r = measure_attribution_density(text)
        assert r.explicit_attribution_count >= 1
        assert r.total_sentences == 2
        assert r.attribution_sentence_ratio > 0.3

    def test_very_short_no_attribution(self):
        r = measure_attribution_density("Just a test.")
        assert r.attribution_density_index == 0.0
        assert r.classification == "unattributed"


# ── traceability scoring ───────────────────────────────────────


class TestTraceability:
    def test_purely_traceable(self):
        """All explicit attributions are traceable."""
        text = (
            "According to Smith, the result holds. "
            "As noted by Jones, the method works. "
            "According to the data, growth continued. "
            "According to the report, costs declined."
        )
        r = measure_attribution_density(text)
        if r.explicit_attribution_count > 0:
            assert r.traceability_score >= 0.5

    def test_purely_untraceable(self):
        """Weasel and consensus attributions are untraceable."""
        text = (
            "Some people say it works. "
            "It is widely believed that the method is sound. "
            "Studies show positive results. "
            "Critics argue the approach is flawed. "
            "Many reports confirm the trend. "
            "It is commonly known that costs declined."
        )
        r = measure_attribution_density(text)
        assert r.traceability_score < 0.5


# ── composite index properties ─────────────────────────────────


class TestCompositeIndex:
    def test_index_bounded_zero_one(self):
        """Index should always be between 0 and 1."""
        texts = [
            "Simple sentence with no attribution at all.",
            "According to everyone, studies show experts agree "
            "it is widely known that some people say it was "
            "reported that the consensus supports this claim.",
            "",
            "A mix. According to Smith, yes. But also no.",
        ]
        for text in texts:
            r = measure_attribution_density(text)
            assert 0.0 <= r.attribution_density_index <= 1.0

    def test_more_attribution_higher_index(self):
        """More attribution should produce higher index."""
        low = "The cat sat on the mat. The dog ran in the park. "
        low += "Birds flew overhead. The sun set slowly."

        high = (
            "According to Smith, the cat sat on the mat. "
            "As noted by Jones, the dog ran in the park. "
            "Experts agree that birds fly overhead. "
            "Studies show the sun sets slowly."
        )
        r_low = measure_attribution_density(low)
        r_high = measure_attribution_density(high)
        assert r_high.attribution_density_index > r_low.attribution_density_index

    def test_classification_ordering(self):
        """Classifications should follow index thresholds."""
        r = measure_attribution_density(
            "According to everyone everywhere, experts agree "
            "studies show it is widely known that researchers "
            "found scientists warn analysts note reports indicate "
            "sources say critics argue observers suggest most "
            "experts believe the consensus supports this view."
        )
        if r.attribution_density_index >= 0.60:
            assert r.classification == "source_saturated"
        elif r.attribution_density_index >= 0.35:
            assert r.classification == "heavily_attributed"
        elif r.attribution_density_index >= 0.15:
            assert r.classification == "moderately_attributed"
        elif r.attribution_density_index >= 0.05:
            assert r.classification == "lightly_attributed"
        else:
            assert r.classification == "unattributed"


# ── details dict ───────────────────────────────────────────────


class TestDetailsDict:
    def test_details_contains_all_keys(self):
        r = measure_attribution_density("According to Smith, yes.")
        expected_keys = {
            "explicit_attribution_rate",
            "quoted_speech_rate",
            "expert_appeal_rate",
            "consensus_appeal_rate",
            "weasel_attribution_rate",
            "reported_speech_rate",
            "source_pattern_rate",
            "attribution_sentence_ratio",
            "source_diversity_index",
            "traceability_score",
            "attribution_density_index",
            "classification",
        }
        assert set(r.details.keys()) == expected_keys

    def test_details_values_match_fields(self):
        r = measure_attribution_density(
            "According to experts, studies show it is known."
        )
        assert r.details["explicit_attribution_rate"] == r.explicit_attribution_rate
        assert r.details["classification"] == r.classification
        assert r.details["traceability_score"] == r.traceability_score


# ── orthogonality checks ───────────────────────────────────────


class TestOrthogonality:
    def test_not_hedging(self):
        """Attribution != hedging. Text with hedges but no attribution."""
        text = (
            "It might be true that the effect exists. "
            "Perhaps the method works to some extent. "
            "The results could possibly indicate a trend. "
            "It seems likely that something happened."
        )
        r = measure_attribution_density(text)
        # Few attribution markers despite hedging language
        assert r.attribution_density_index < 0.15

    def test_not_citation_format(self):
        """Attribution is rhetorical, not formal citation."""
        text = (
            "The result was significant [1]. Another study [2] "
            "validated the findings [3]. The method [4] proved "
            "effective [5]. Previous work [6][7] established "
            "the baseline [8]."
        )
        r = measure_attribution_density(text)
        # Bracket citations are not rhetorical attribution
        assert r.explicit_attribution_count == 0
        # Most bracket citations should not trigger attribution
        assert r.attribution_density_index < 0.35

    def test_not_deixis(self):
        """Attribution is self-contained, not context-dependent."""
        text = (
            "He told her about it there. She pointed to that "
            "thing over there. They discussed this and that. "
            "I remember when we went there together."
        )
        r = measure_attribution_density(text)
        assert r.explicit_attribution_count == 0
        assert r.consensus_appeal_count == 0
        assert r.expert_appeal_count == 0


# ── result dataclass defaults ──────────────────────────────────


class TestResultDefaults:
    def test_default_result(self):
        r = AttributionDensityResult()
        assert r.attribution_density_index == 0.0
        assert r.classification == "unattributed"
        assert r.total_sentences == 0
        assert r.explicit_attribution_count == 0
        assert r.quoted_speech_count == 0
        assert r.traceability_score == 0.0
        assert r.source_diversity_index == 0.0
        assert r.details == {}


# ── idempotency ────────────────────────────────────────────────


class TestIdempotency:
    def test_same_input_same_result(self):
        text = (
            "According to Smith, the study confirms the theory. "
            "Experts agree the results are reproducible. "
            "It is widely accepted that the method is sound."
        )
        r1 = measure_attribution_density(text)
        r2 = measure_attribution_density(text)
        assert r1.attribution_density_index == r2.attribution_density_index
        assert r1.classification == r2.classification
        assert r1.explicit_attribution_count == r2.explicit_attribution_count
        assert r1.traceability_score == r2.traceability_score
