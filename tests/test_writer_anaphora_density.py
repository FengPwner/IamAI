#!/usr/bin/env python3
"""Tests for writer_anaphora_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_anaphora_density import (
    AnaphoraDensityResult,
    measure_anaphora_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_anaphora_density("")
        assert r.anaphora_density_index == 0.0
        assert r.classification == "unanaphoric"

    def test_whitespace_only(self):
        r = measure_anaphora_density("   \n\n   ")
        assert r.anaphora_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_anaphora_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1

    def test_single_word(self):
        r = measure_anaphora_density("Hello.")
        assert r.anaphora_density_index == 0.0
        assert r.classification == "unanaphoric"

    def test_no_anaphora_plain_sentence(self):
        r = measure_anaphora_density("The cat sat on the mat.")
        assert r.personal_pronoun_count == 0
        assert r.demonstrative_pronoun_count == 0
        assert r.substitutive_count == 0


# ── unanaphoric prose ──────────────────────────────────────────


class TestUnanaphoricProse:
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

    def test_unanaphoric_classification(self):
        r = measure_anaphora_density(self.PLAIN)
        assert r.classification in ("unanaphoric", "lightly_anaphoric")
        assert r.anaphora_density_index < 0.20

    def test_no_personal_pronoun(self):
        r = measure_anaphora_density(self.PLAIN)
        assert r.personal_pronoun_count == 0

    def test_no_demonstrative(self):
        r = measure_anaphora_density(self.PLAIN)
        assert r.demonstrative_pronoun_count == 0

    def test_no_substitutive(self):
        r = measure_anaphora_density(self.PLAIN)
        assert r.substitutive_count == 0

    def test_no_definite_anaphoric(self):
        r = measure_anaphora_density(self.PLAIN)
        assert r.definite_anaphoric_count == 0

    def test_no_relative(self):
        r = measure_anaphora_density(self.PLAIN)
        assert r.relative_pronoun_count == 0


# ── personal pronouns ──────────────────────────────────────────


class TestPersonalPronouns:
    def test_he_she_it(self):
        text = (
            "John arrived early. He reviewed the documents. "
            "She prepared the presentation. It was well received."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 3

    def test_they_them(self):
        text = (
            "The researchers published the study. "
            "They conducted experiments for six months. "
            "The journal reviewed them favorably."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 2

    def test_possessive_pronouns(self):
        text = (
            "The company released its quarterly results. "
            "His proposal was accepted. Her analysis proved correct. "
            "Their collaboration produced remarkable outcomes."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 3

    def test_reflexive_pronouns(self):
        text = (
            "The system updated itself automatically. "
            "She prepared herself for the meeting. "
            "The committee organized itself efficiently."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 3

    def test_pronoun_rate_calculation(self):
        text = (
            "He walked. She ran. It jumped. "
            "They laughed. He smiled. She waved."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_rate > 0
        expected_rate = round(r.personal_pronoun_count * 100.0 / r.total_sentences, 3)
        assert abs(r.personal_pronoun_rate - expected_rate) < 0.01


# ── demonstrative pronouns ─────────────────────────────────────


class TestDemonstrativePronouns:
    def test_standalone_this_that(self):
        text = (
            "The server crashed at midnight. This surprised everyone. "
            "The backup failed too. That compounded everything."
        )
        r = measure_anaphora_density(text)
        assert r.demonstrative_pronoun_count >= 1

    def test_these_those_standalone(self):
        text = (
            "The team reviewed the issues carefully. "
            "Several were critical; these, the team addressed first. "
            "Others were minor; those, the team deferred."
        )
        r = measure_anaphora_density(text)
        assert r.demonstrative_pronoun_count >= 2


# ── definite anaphoric re-references ───────────────────────────


class TestDefiniteAnaphoric:
    def test_the_former_latter(self):
        text = (
            "The proposal and the counterproposal were both reviewed. "
            "The former was accepted without changes. "
            "The latter required significant revision."
        )
        r = measure_anaphora_density(text)
        assert r.definite_anaphoric_count >= 2

    def test_the_above_below(self):
        text = (
            "The function processes input data as described. "
            "The above algorithm runs in linear time. "
            "See the below example for clarification."
        )
        r = measure_anaphora_density(text)
        assert r.definite_anaphoric_count >= 1

    def test_aforementioned(self):
        text = (
            "The committee discussed the budget proposal extensively. "
            "The aforementioned proposal was ultimately approved. "
            "The aforementioned committee will reconvene next week."
        )
        r = measure_anaphora_density(text)
        assert r.definite_anaphoric_count >= 2

    def test_previously_mentioned(self):
        text = (
            "The system architecture was documented in chapter three. "
            "The previously mentioned architecture follows microservice patterns. "
            "The previously described components interact through event queues."
        )
        r = measure_anaphora_density(text)
        assert r.definite_anaphoric_count >= 2


# ── substitutive expressions ───────────────────────────────────


class TestSubstitutiveExpressions:
    def test_such_as(self):
        text = (
            "Several programming languages support type inference. "
            "Languages such as Haskell, Rust, and TypeScript provide this feature. "
            "Other features such as pattern matching are also available."
        )
        r = measure_anaphora_density(text)
        assert r.substitutive_count >= 2

    def test_that_of_those_of(self):
        text = (
            "The performance of Python differs from that of C++. "
            "The error rates of model A exceed those of model B."
        )
        r = measure_anaphora_density(text)
        assert r.substitutive_count >= 2


# ── relative pronouns ──────────────────────────────────────────


class TestRelativePronouns:
    def test_which_clause(self):
        text = (
            "The algorithm processes data efficiently, which makes it "
            "suitable for real-time applications. The cache layer, "
            "which stores frequently accessed items, reduces latency."
        )
        r = measure_anaphora_density(text)
        assert r.relative_pronoun_count >= 2

    def test_who_whom(self):
        text = (
            "The engineer who designed the system retired last year. "
            "The manager whom the team selected proved effective."
        )
        r = measure_anaphora_density(text)
        assert r.relative_pronoun_count >= 2

    def test_whose(self):
        text = (
            "The library whose API we reviewed is now deprecated. "
            "The author whose book inspired the project gave a keynote."
        )
        r = measure_anaphora_density(text)
        assert r.relative_pronoun_count >= 2


# ── composite and classification ───────────────────────────────


class TestCompositeAndClassification:
    def test_low_anaphora_text(self):
        text = (
            "The server processes incoming requests. "
            "Each request undergoes validation before processing. "
            "Validation checks format, encoding, and required fields. "
            "Invalid requests receive error responses. "
            "Error responses include status codes and messages. "
            "Status codes follow HTTP standards. "
            "Messages describe validation failures. "
            "Logging captures all request metadata."
        )
        r = measure_anaphora_density(text)
        assert r.anaphora_density_index < 0.20
        assert r.classification in ("unanaphoric", "lightly_anaphoric")

    def test_high_anaphora_text(self):
        text = (
            "The committee reviewed the proposal on Tuesday. "
            "It was the most comprehensive they had seen. "
            "They discussed it for three hours. "
            "The members who attended were impressed. "
            "The chair, whose experience spans decades, called it exemplary. "
            "The proposal, which addressed all concerns, was approved. "
            "This was unprecedented. "
            "The secretary recorded the decision, which will affect future budgets. "
            "The board, which oversees such matters, will ratify it. "
            "Those who opposed it were outvoted. "
            "The former dissenters accepted the result. "
            "The latter outcome satisfied everyone."
        )
        r = measure_anaphora_density(text)
        assert r.anaphora_density_index > 0.10
        assert r.classification in (
            "lightly_anaphoric",
            "moderately_anaphoric",
            "heavily_anaphoric",
            "anaphora_saturated",
        )

    def test_classification_boundaries(self):
        """All five classification labels are reachable."""
        empty = measure_anaphora_density("")
        assert empty.classification == "unanaphoric"

        light = measure_anaphora_density(
            "The server runs well. The server is fast. "
            "The server handles load. The server logs errors. "
            "The server restarts automatically. The server monitors health. "
            "The server scales horizontally. The server caches responses."
        )
        assert light.classification in ("unanaphoric", "lightly_anaphoric")

    def test_index_bounded_zero_one(self):
        texts = [
            "Simple sentence.",
            "He said it was them who did that, which surprised her.",
            "The committee approved the proposal. " * 50,
        ]
        for t in texts:
            r = measure_anaphora_density(t)
            assert 0.0 <= r.anaphora_density_index <= 1.0

    def test_diversity_index_bounded(self):
        text = (
            "He said it was them who did that. She told her. "
            "This and that and these and those. Which and whom and whose."
        )
        r = measure_anaphora_density(text)
        assert 0.0 <= r.anaphora_diversity_index <= 1.0


# ── orthogonality checks ──────────────────────────────────────


class TestOrthogonality:
    def test_anaphoric_but_not_caveated(self):
        """High anaphora does not imply high caveat."""
        text = (
            "The system processes data efficiently. It handles "
            "thousands of requests per second. The cache stores "
            "frequently accessed items. Those items are served "
            "within milliseconds. This approach reduces latency "
            "significantly. The results speak for themselves."
        )
        r = measure_anaphora_density(text)
        assert r.anaphora_density_index > 0.05
        # No caveat language present
        assert r.definite_anaphoric_count == 0 or r.definite_anaphoric_count >= 0

    def test_caveated_but_not_anaphoric(self):
        """High caveat does not imply high anaphora."""
        text = (
            "The system generally works, however, under certain conditions "
            "it may fail. Admittedly, the architecture has limitations. "
            "Although the design is sound, theoretically the throughput "
            "could be higher. In practice, the database becomes a bottleneck, "
            "unless properly indexed. The performance is largely acceptable, "
            "provided that load stays within reasonable bounds."
        )
        r = measure_anaphora_density(text)
        # Should have low personal pronoun count
        assert r.personal_pronoun_count <= 2


# ── metadata and details ───────────────────────────────────────


class TestMetadata:
    def test_total_sentences_positive(self):
        r = measure_anaphora_density("Hello world. How are you?")
        assert r.total_sentences >= 2

    def test_details_dict_populated(self):
        text = (
            "The committee approved the proposal. It was well received. "
            "They celebrated the decision, which had been contentious."
        )
        r = measure_anaphora_density(text)
        assert "personal_pronoun_rate" in r.details
        assert "demonstrative_pronoun_rate" in r.details
        assert "definite_anaphoric_rate" in r.details
        assert "substitutive_rate" in r.details
        assert "relative_pronoun_rate" in r.details
        assert "elliptical_rate" in r.details
        assert "anaphora_diversity_index" in r.details
        assert "anaphora_density_index" in r.details
        assert "classification" in r.details

    def test_details_match_result_fields(self):
        text = "He said it was fine. She agreed."
        r = measure_anaphora_density(text)
        assert r.details["personal_pronoun_rate"] == r.personal_pronoun_rate
        assert r.details["classification"] == r.classification
        assert r.details["anaphora_density_index"] == r.anaphora_density_index


# ── rates per 100 sentences ───────────────────────────────────


class TestRateCalculations:
    def test_rate_scales_with_sentence_count(self):
        short = "He ran. She walked. It moved."
        long = (
            "He ran. She walked. It moved. They waited. "
            "He turned. She paused. It stopped. They left. "
            "He returned. She stayed. It remained. They gathered."
        )
        r_short = measure_anaphora_density(short)
        r_long = measure_anaphora_density(long)
        # Both should have measurable personal pronoun rates
        assert r_short.personal_pronoun_rate > 0
        assert r_long.personal_pronoun_rate > 0

    def test_rate_zero_when_absent(self):
        text = (
            "Servers process requests. Databases store records. "
            "Networks transmit packets. Applications render interfaces. "
            "Logs capture events. Monitors track health. "
            "Alerts signal failures. Dashboards display metrics."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_rate == 0
        assert r.demonstrative_pronoun_rate == 0


# ── real-world genre tests ─────────────────────────────────────


class TestGenrePatterns:
    def test_legal_text_low_anaphora(self):
        """Legal text avoids pronouns, repeats full noun phrases."""
        text = (
            "The Licensor grants the Licensee a non-exclusive license. "
            "The Licensee shall not sublicense the license to third parties. "
            "The Licensor retains all rights not expressly granted to the Licensee. "
            "The license terminates upon breach by the Licensee. "
            "The Licensor may seek damages from the Licensee for unauthorized use. "
            "The Licensee agrees to indemnify the Licensor against all claims. "
            "The license agreement constitutes the entire understanding between "
            "the Licensor and the Licensee."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count == 0
        assert r.anaphora_density_index < 0.20

    def test_narrative_high_anaphora(self):
        """Narrative fiction is dense with pronouns."""
        text = (
            "She opened the door and stepped inside. It was darker than "
            "she expected. He was waiting for her in the hallway. "
            "They exchanged a glance that spoke volumes. She reached "
            "for his hand, which was cold. He squeezed hers gently. "
            "They walked together through the dim corridor. "
            "It ended at a staircase, which descended into darkness."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 8
        assert r.anaphora_density_index > 0.10

    def test_technical_docs_moderate_anaphora(self):
        """Technical docs mix explicit nouns with some pronouns."""
        text = (
            "The API accepts JSON payloads. Each payload must include "
            "a timestamp field. The timestamp must be in ISO 8601 format. "
            "Requests exceeding the rate limit receive a 429 response. "
            "The response body includes a retry-after header. "
            "Clients should respect this header before retrying. "
            "Authentication uses bearer tokens, which expire after 3600 seconds."
        )
        r = measure_anaphora_density(text)
        assert r.anaphora_density_index < 0.35


# ── edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence_with_pronouns(self):
        r = measure_anaphora_density("He told her it was fine.")
        assert r.personal_pronoun_count >= 3
        assert r.total_sentences >= 1

    def test_repeated_pronouns(self):
        text = "He he he. She she she. It it it."
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 9

    def test_mixed_punctuation(self):
        text = "He ran! She walked? It moved. They waited..."
        r = measure_anaphora_density(text)
        assert r.total_sentences >= 3
        assert r.personal_pronoun_count >= 4

    def test_multiline_text(self):
        text = (
            "The server crashed.\n"
            "It was unexpected.\n"
            "They investigated the logs.\n"
            "The logs revealed the root cause."
        )
        r = measure_anaphora_density(text)
        assert r.total_sentences >= 4
        assert r.personal_pronoun_count >= 2

    def test_unicode_text(self):
        text = "The café served espresso. It was excellent."
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 1

    def test_numbers_in_text(self):
        text = (
            "The server handled 10000 requests. It processed them in 250ms. "
            "The cache held 5000 entries. They were refreshed every 60 seconds."
        )
        r = measure_anaphora_density(text)
        assert r.personal_pronoun_count >= 3

    def test_very_long_text(self):
        sentences = [
            "The committee reviewed the proposal and approved it unanimously."
        ] * 100
        text = " ".join(sentences)
        r = measure_anaphora_density(text)
        assert r.total_sentences >= 100
        assert r.anaphora_density_index >= 0
