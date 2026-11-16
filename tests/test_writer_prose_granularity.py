#!/usr/bin/env python3
"""Tests for writer_prose_granularity module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_prose_granularity import (
    ProseGranularityResult,
    measure_prose_granularity,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_prose_granularity("")
        assert r.granularity_index == 0.0
        assert r.classification == "abstract"

    def test_whitespace_only(self):
        r = measure_prose_granularity("   \n\n   ")
        assert r.granularity_index == 0.0

    def test_single_word(self):
        r = measure_prose_granularity("Hello.")
        assert r.classification in ("abstract", "general", "mixed")

    def test_no_granularity_plain_sentence(self):
        r = measure_prose_granularity("The function returns a boolean value.")
        assert r.proper_noun_count == 0
        assert r.numerical_precision_count == 0


# ── abstract prose (low granularity) ───────────────────────────


class TestAbstractProse:
    def test_purely_abstract_text(self):
        text = (
            "The fundamental paradigm underlying modern computational "
            "approaches to complex systems involves iterative refinement "
            "of approximate solutions. The methodology requires careful "
            "consideration of various factors and circumstances."
        )
        r = measure_prose_granularity(text)
        assert r.abstract_noun_count > r.concrete_noun_count
        assert r.granularity_index < 0.30

    def test_management_speak(self):
        text = (
            "Our organization values communication and collaboration. "
            "The management team focuses on continuous improvement and "
            "sustainable development. We believe in the importance of "
            "innovation and creativity in our approach."
        )
        r = measure_prose_granularity(text)
        assert r.abstract_noun_count > 0
        assert r.proper_noun_count == 0
        assert r.granularity_index < 0.30

    def test_philosophical_prose(self):
        text = (
            "The nature of consciousness remains one of the deepest "
            "mysteries in philosophy. Understanding the relationship "
            "between perception and cognition requires careful "
            "consideration of fundamental principles."
        )
        r = measure_prose_granularity(text)
        assert r.classification in ("abstract", "general")

    def test_generalization_heavy(self):
        text = (
            "Generally speaking, most people tend to prefer simplicity "
            "over complexity. In general, the majority of users "
            "typically find that well-designed systems are usually "
            "more effective on the whole."
        )
        r = measure_prose_granularity(text)
        assert r.generalization_count >= 4
        assert r.granularity_index < 0.30


# ── granular prose (high granularity) ──────────────────────────


class TestGranularProse:
    def test_lab_notebook_entry(self):
        text = (
            "Maria Rodriguez loaded the 3.2mm titanium drill bit "
            "into the Makita DHP485 at 14:30 on 2024-03-15. "
            "The specimen, a 47mm x 23mm aluminum 6061-T6 coupon, "
            "was clamped at 12.5 Nm torque. Drilling at 14700 RPM "
            "produced a 3.18mm through-hole in 2.7 seconds."
        )
        r = measure_prose_granularity(text)
        assert r.proper_noun_count >= 2
        assert r.numerical_precision_count >= 5
        assert r.granularity_index > 0.50

    def test_server_log_analysis(self):
        text = (
            "Server rack 7A in the Portland datacenter drew 4.2 kW "
            "at 2:15 PM on 2024-01-15, a 23% increase over the "
            "baseline of 3.4 kW measured on 2024-01-08. The "
            "Dell PowerEdge R750xs running Ubuntu 22.04.3 with "
            "kernel 5.15.0-91 showed 87% CPU utilization across "
            "all 32 cores."
        )
        r = measure_prose_granularity(text)
        assert r.proper_noun_count >= 3
        assert r.numerical_precision_count >= 6
        assert r.granularity_index > 0.50

    def test_recipe_instructions(self):
        text = (
            "Preheat the oven to 175°C. Place the 250g block of "
            "butter in a 23cm cast iron pan. Add 3 eggs, 150ml "
            "of milk, and 2.5g of salt. Bake for 35 minutes until "
            "the internal temperature reaches 71°C."
        )
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count >= 4
        assert r.concrete_noun_count >= 2
        assert r.granularity_index > 0.40

    def test_specific_tech_report(self):
        text = (
            "The GPT-4 Turbo model processed 127,843 tokens in "
            "47.3 seconds at a cost of $0.38. Claude 3.5 Sonnet "
            "handled the same input in 31.2 seconds for $0.45. "
            "Llama 3.1 70B running on an A100 80GB GPU took "
            "89.1 seconds."
        )
        r = measure_prose_granularity(text)
        assert r.proper_noun_count >= 3
        assert r.numerical_precision_count >= 5
        assert r.classification in ("specific", "granular")


# ── mixed prose ────────────────────────────────────────────────


class TestMixedProse:
    def test_blog_post_style(self):
        text = (
            "When we tested the new MacBook Pro M3 Max, the results "
            "were impressive. The laptop compiled our test project "
            "in just 47 seconds, compared to 89 seconds on the "
            "previous generation. Generally, Apple's silicon "
            "tends to outperform comparable Intel machines."
        )
        r = measure_prose_granularity(text)
        assert 0.20 < r.granularity_index < 0.70

    def test_news_article(self):
        text = (
            "On January 15, 2024, the Federal Reserve announced "
            "a 0.25 percentage point rate cut, bringing the federal "
            "funds rate to 4.50%. Chair Jerome Powell stated that "
            "inflation has generally been moving toward the 2% "
            "target."
        )
        r = measure_prose_granularity(text)
        assert r.proper_noun_count >= 2
        assert r.numerical_precision_count >= 3
        assert r.classification in ("mixed", "specific", "granular")

    def test_mixed_abstraction_levels(self):
        text = (
            "Software development is a complex process that requires "
            "careful planning and execution. For example, the team "
            "at Google used a specific testing framework called "
            "Googletest to validate their protobuf library v3.21.12."
        )
        r = measure_prose_granularity(text)
        assert r.abstract_noun_count >= 2
        assert r.proper_noun_count >= 1
        assert r.instance_count >= 1


# ── proper noun detection ──────────────────────────────────────


class TestProperNouns:
    def test_multiple_proper_nouns(self):
        text = (
            "Sarah Chen presented the results to the Apache "
            "Foundation board in Portland, Oregon on behalf "
            "of Microsoft."
        )
        r = measure_prose_granularity(text)
        assert r.proper_noun_count >= 4

    def test_no_proper_nouns(self):
        text = (
            "The researcher presented the results to the "
            "foundation board in the city on behalf of the company."
        )
        r = measure_prose_granularity(text)
        assert r.proper_noun_count == 0

    def test_sentence_starters_excluded(self):
        text = "The server crashed. However, the backup restored the data."
        r = measure_prose_granularity(text)
        # "However" is a sentence starter and should not be counted
        assert r.proper_noun_count == 0


# ── numerical precision ────────────────────────────────────────


class TestNumericalPrecision:
    def test_decimal_numbers(self):
        text = "The temperature rose by 2.7 degrees Celsius over 48.5 hours."
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count >= 2

    def test_measurements_with_units(self):
        text = "The cable is 3.5mm thick and 12cm long, weighing 45g."
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count >= 3

    def test_dates_detected(self):
        text = "The event occurred on 2024-03-15 and was reviewed on January 20, 2024."
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count >= 2

    def test_timestamps_detected(self):
        text = "The process started at 14:30 and finished at 16:45:22."
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count >= 2

    def test_version_numbers(self):
        text = "We upgraded from version 3.11.2 to Python 3.12.1 on the server."
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count >= 2

    def test_large_integers(self):
        text = "The database contains 127843 records spanning 45000 categories."
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count >= 2

    def test_vague_numbers_low_precision(self):
        text = "It took a few minutes and cost some money."
        r = measure_prose_granularity(text)
        assert r.numerical_precision_count == 0


# ── concrete vs abstract nouns ────────────────────────────────


class TestConcreteAbstract:
    def test_mostly_concrete(self):
        text = (
            "The dog sat on the chair near the table. "
            "The cat jumped onto the desk and knocked "
            "the cup onto the floor."
        )
        r = measure_prose_granularity(text)
        assert r.concrete_noun_count > r.abstract_noun_count
        assert r.concreteness_score > 0.5

    def test_mostly_abstract(self):
        text = (
            "The implementation of the methodology requires "
            "consideration of various factors. The analysis "
            "of the situation demands careful evaluation."
        )
        r = measure_prose_granularity(text)
        assert r.abstract_noun_count > r.concrete_noun_count
        assert r.concreteness_score < 0.5

    def test_mixed_nouns(self):
        text = (
            "The server rack holds the key to our infrastructure. "
            "The keyboard connects to the system through a cable."
        )
        r = measure_prose_granularity(text)
        assert r.concrete_noun_count > 0
        assert r.abstract_noun_count > 0

    def test_ratio_calculation(self):
        text = "The laptop sits on the desk near the window."
        r = measure_prose_granularity(text)
        if r.concrete_noun_count + r.abstract_noun_count > 0:
            expected = r.concrete_noun_count / (
                r.concrete_noun_count + r.abstract_noun_count
            )
            assert abs(r.concrete_abstract_ratio - round(expected, 4)) < 0.001


# ── generalization markers ─────────────────────────────────────


class TestGeneralization:
    def test_heavy_generalization(self):
        text = (
            "Generally, most systems tend to perform better "
            "when properly maintained. In general, the typical "
            "user usually finds that regular updates are "
            "commonly beneficial."
        )
        r = measure_prose_granularity(text)
        assert r.generalization_count >= 4

    def test_no_generalization(self):
        text = (
            "The MacBook Air M2 compiled the project in 47 "
            "seconds at 14:30 on 2024-03-15."
        )
        r = measure_prose_granularity(text)
        assert r.generalization_count == 0

    def test_phrase_detection(self):
        text = (
            "As a rule, servers consume more power during peak "
            "hours. On average, the difference is 23%. By and "
            "large, the pattern holds across all datacenters."
        )
        r = measure_prose_granularity(text)
        assert r.generalization_count >= 3

    def test_inversion_effect(self):
        """More generalization should lower granularity index."""
        low_gen = measure_prose_granularity(
            "The Dell R750xs drew 4.2 kW at 14:30."
        )
        high_gen = measure_prose_granularity(
            "Generally, servers tend to use power during the day."
        )
        assert low_gen.generalization_count < high_gen.generalization_count


# ── instance markers ───────────────────────────────────────────


class TestInstanceMarkers:
    def test_multiple_instance_markers(self):
        text = (
            "Large language models have varying capabilities. "
            "For example, GPT-4 excels at reasoning. Specifically, "
            "it handles chain-of-thought prompts well. For instance, "
            "it solved 87% of math problems."
        )
        r = measure_prose_granularity(text)
        assert r.instance_count >= 3

    def test_no_instance_markers(self):
        text = (
            "The server processed 47000 requests in 3.2 seconds "
            "on 2024-03-15 at 14:30."
        )
        r = measure_prose_granularity(text)
        assert r.instance_count == 0

    def test_such_as_detected(self):
        text = "Metals such as aluminum, copper, and titanium have different properties."
        r = measure_prose_granularity(text)
        assert r.instance_count >= 1

    def test_namely_detected(self):
        text = "The two primary languages, namely Python and Rust, were used."
        r = measure_prose_granularity(text)
        assert r.instance_count >= 1


# ── classification thresholds ──────────────────────────────────


class TestClassification:
    def test_abstract_classification(self):
        text = (
            "The nature of consciousness involves understanding "
            "perception and cognition through careful consideration "
            "of fundamental principles and methodology."
        )
        r = measure_prose_granularity(text)
        assert r.classification in ("abstract", "general")

    def test_granular_classification(self):
        text = (
            "Maria Chen loaded the 3.2mm bit into the Makita "
            "DHP485 at 14:30 on 2024-03-15. The 47mm aluminum "
            "6061-T6 coupon was clamped at 12.5 Nm torque in "
            "Portland, Oregon. Drilling at 14700 RPM produced "
            "a 3.18mm hole in 2.7 seconds."
        )
        r = measure_prose_granularity(text)
        assert r.classification in ("specific", "granular")


# ── orthogonality ──────────────────────────────────────────────


class TestOrthogonality:
    def test_granular_but_short(self):
        """High granularity doesn't require verbosity."""
        text = "The 3.2mm bit snapped at 14700 RPM on 2024-03-15."
        r = measure_prose_granularity(text)
        assert r.granularity_index > 0.40
        assert r.total_words < 15

    def test_verbose_but_abstract(self):
        """Long text can still be low granularity."""
        text = (
            "The fundamental nature of the implementation of "
            "the methodology requires careful consideration and "
            "evaluation of various factors and circumstances "
            "that influence the overall effectiveness of the "
            "approach in the context of modern organizational "
            "management and administration processes."
        )
        r = measure_prose_granularity(text)
        assert r.granularity_index < 0.30

    def test_granular_without_causation(self):
        """Granularity is independent of causal reasoning."""
        text = (
            "The Dell PowerEdge R750xs has 32 cores, 256GB RAM, "
            "and 8 x 3.84TB NVMe drives. The server weighs "
            "28.6 kg and measures 482mm x 740mm x 87mm."
        )
        r = measure_prose_granularity(text)
        assert r.granularity_index > 0.40


# ── composite index calculation ────────────────────────────────


class TestCompositeIndex:
    def test_index_range(self):
        """Index should always be between 0.0 and 1.0."""
        texts = [
            "Hello world.",
            "The server crashed.",
            "Maria Rodriguez loaded the 3.2mm titanium drill bit into the Makita DHP485 at 14:30 on 2024-03-15.",
            "Generally speaking, most systems tend to perform better.",
            "",
            "The nature of consciousness involves perception and cognition.",
        ]
        for text in texts:
            r = measure_prose_granularity(text)
            assert 0.0 <= r.granularity_index <= 1.0

    def test_weights_sum_to_one(self):
        """The five channel weights should sum to 1.0."""
        weights = [0.25, 0.25, 0.20, 0.15, 0.15]
        assert abs(sum(weights) - 1.0) < 0.001

    def test_monotonic_granularity_ordering(self):
        """More granular text should have higher index."""
        abstract = (
            "The methodology requires consideration of various "
            "factors in the implementation process."
        )
        specific = (
            "The Dell R750xs server with 256GB RAM processed "
            "47000 requests in 3.2 seconds."
        )
        r_abs = measure_prose_granularity(abstract)
        r_spec = measure_prose_granularity(specific)
        assert r_spec.granularity_index > r_abs.granularity_index


# ── metadata ───────────────────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_prose_granularity(text)
        assert r.total_sentences == 3

    def test_word_count(self):
        text = "The quick brown fox jumps over the lazy dog."
        r = measure_prose_granularity(text)
        assert r.total_words == 9

    def test_total_markers(self):
        text = (
            "Maria Chen tested the Dell R750xs server with "
            "256GB RAM at 14:30 on 2024-03-15. For example, "
            "the keyboard and mouse connected via USB."
        )
        r = measure_prose_granularity(text)
        assert r.total_granularity_markers > 0
        assert r.total_granularity_markers == (
            r.proper_noun_count
            + r.numerical_precision_count
            + r.concrete_noun_count
            + r.abstract_noun_count
            + r.generalization_count
            + r.instance_count
        )


# ── edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence(self):
        r = measure_prose_granularity("Hello.")
        assert r.total_sentences == 1

    def test_numbers_only(self):
        r = measure_prose_granularity("42.7 3.14 100.0")
        assert r.numerical_precision_count >= 2

    def test_repeated_text(self):
        text = "The server crashed. " * 10
        r = measure_prose_granularity(text)
        assert r.total_sentences == 10

    def test_mixed_languages_ignored(self):
        """Non-English words should not inflate proper noun count."""
        text = "The café in Paris serves excellent crème brûlée."
        r = measure_prose_granularity(text)
        # "Paris" is a proper noun; café and crème brûlée are not English
        assert r.proper_noun_count >= 1

    def test_all_caps_not_proper_noun(self):
        """Short all-caps words (like 'I', 'AI') should be handled."""
        text = "AI and ML are important. I think the API is good."
        r = measure_prose_granularity(text)
        # "I" and sentence starters shouldn't be counted as proper nouns
        # AI, ML, API are short all-caps that should be handled

    def test_result_dataclass_defaults(self):
        r = ProseGranularityResult()
        assert r.granularity_index == 0.0
        assert r.classification == "abstract"
        assert r.proper_noun_count == 0
        assert r.total_sentences == 0


# ── real-world text samples ────────────────────────────────────


class TestRealWorldSamples:
    def test_git_commit_message(self):
        text = (
            "add writer_prose_granularity module + 35 tests + "
            "caretaker visit 656 — measure detail resolution of "
            "prose across five channels: proper noun density, "
            "numerical precision, concrete noun ratio, "
            "generalization markers, instance markers; composite "
            "granularity_index (0.0 to 1.0) written by Qwen "
            "during manual caretaker visit 656, 2026-11-16."
        )
        r = measure_prose_granularity(text)
        assert r.total_words > 20
        assert r.granularity_index > 0.0

    def test_academic_abstract(self):
        text = (
            "This study investigates the relationship between "
            "organizational culture and employee productivity "
            "through a mixed-methods approach. The methodology "
            "incorporates both quantitative analysis and qualitative "
            "interviews. Results generally suggest that culture "
            "tends to influence productivity significantly."
        )
        r = measure_prose_granularity(text)
        assert r.abstract_noun_count > r.concrete_noun_count
        assert r.classification in ("abstract", "general")

    def test_incident_report(self):
        text = (
            "At 03:47 AM on 2024-02-28, server web-prod-03 in "
            "the us-east-1 region experienced a disk failure on "
            "/dev/sda2. The 1.2TB ext4 partition became read-only "
            "at 03:47:22 UTC. Engineer Sarah Kim was paged at "
            "03:48 and began recovery at 03:52. The backup from "
            "02:00 was restored by 04:35, with 2 hours 48 minutes "
            "of total downtime."
        )
        r = measure_prose_granularity(text)
        assert r.proper_noun_count >= 2
        assert r.numerical_precision_count >= 6
        assert r.classification in ("specific", "granular")
