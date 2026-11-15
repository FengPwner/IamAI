#!/usr/bin/env python3
"""Tests for writer_exemplification_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_exemplification_density import (
    ExemplificationResult,
    measure_exemplification,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_exemplification("")
        assert r.exemplification_index == 0.0
        assert r.classification == "barren"

    def test_whitespace_only(self):
        r = measure_exemplification("   \n\n   ")
        assert r.exemplification_index == 0.0

    def test_single_word(self):
        r = measure_exemplification("Hello.")
        assert r.classification == "barren"

    def test_no_examples_plain_sentence(self):
        r = measure_exemplification("The committee approved the budget.")
        assert r.explicit_count == 0
        assert r.hypothetical_count == 0
        assert r.analogical_count == 0


# ── barren prose ────────────────────────────────────────────────


class TestBarrenProse:
    BARREN = (
        "The law passed unanimously. "
        "Every senator voted in favor. "
        "The president signed it immediately. "
        "Implementation begins next quarter. "
        "Funding was allocated last month."
    )

    def test_barren_classification(self):
        r = measure_exemplification(self.BARREN)
        assert r.classification in ("barren", "sparse")

    def test_zero_explicit_markers(self):
        r = measure_exemplification(self.BARREN)
        assert r.explicit_count == 0

    def test_zero_hypothetical_markers(self):
        r = measure_exemplification(self.BARREN)
        assert r.hypothetical_count == 0

    def test_low_named_instances(self):
        r = measure_exemplification(self.BARREN)
        assert r.named_instance_count <= 1


# ── explicit exemplification markers ───────────────────────────


class TestExplicitMarkers:
    def test_for_example(self):
        r = measure_exemplification(
            "Many fruits are rich in vitamin C. "
            "For example, oranges and strawberries."
        )
        assert r.explicit_count >= 1

    def test_for_instance(self):
        r = measure_exemplification(
            "Some algorithms fail on large inputs. "
            "For instance, bubble sort degrades quadratically."
        )
        assert r.explicit_count >= 1

    def test_such_as(self):
        r = measure_exemplification(
            "Carnivores such as lions and wolves hunt in packs."
        )
        assert r.explicit_count >= 1

    def test_eg_abbreviation(self):
        r = measure_exemplification(
            "Legumes (e.g., lentils, chickpeas) are protein-rich."
        )
        assert r.explicit_count >= 1

    def test_namely(self):
        r = measure_exemplification(
            "One element dominates the atmosphere, namely nitrogen."
        )
        assert r.explicit_count >= 1

    def test_to_illustrate(self):
        r = measure_exemplification(
            "To illustrate, consider a simple pendulum."
        )
        assert r.explicit_count >= 1

    def test_case_in_point(self):
        r = measure_exemplification(
            "Startups can scale rapidly. "
            "A case in point is the rise of OpenAI."
        )
        assert r.explicit_count >= 1

    def test_take_for_example(self):
        r = measure_exemplification(
            "Take for example the migration patterns of monarch butterflies."
        )
        assert r.explicit_count >= 1

    def test_including(self):
        r = measure_exemplification(
            "Several metals conduct electricity, including copper and aluminum."
        )
        assert r.explicit_count >= 1

    def test_multiple_markers_in_one_text(self):
        text = (
            "Renewable energy sources, such as solar and wind, are growing. "
            "For example, Germany installed 50 GW of solar capacity. "
            "To illustrate, consider the cost reduction since 2010."
        )
        r = measure_exemplification(text)
        assert r.explicit_count >= 3

    def test_explicit_diversity(self):
        text = (
            "For example, cats sleep 16 hours a day. "
            "Such as the Persian breed, which naps even more. "
            "Namely, indoor cats outlive outdoor cats."
        )
        r = measure_exemplification(text)
        assert r.explicit_diversity > 0.0


# ── hypothetical instances ─────────────────────────────────────


class TestHypotheticalInstances:
    def test_imagine(self):
        r = measure_exemplification(
            "Imagine a city where every rooftop has solar panels."
        )
        assert r.hypothetical_count >= 1

    def test_suppose(self):
        r = measure_exemplification(
            "Suppose we double the input size."
        )
        assert r.hypothetical_count >= 1

    def test_picture(self):
        r = measure_exemplification(
            "Picture a forest after a wildfire."
        )
        assert r.hypothetical_count >= 1

    def test_lets_say(self):
        r = measure_exemplification(
            "Let's say you have $1000 to invest."
        )
        assert r.hypothetical_count >= 1

    def test_hypothetically(self):
        r = measure_exemplification(
            "Hypothetically, if gravity were weaker, trees would grow taller."
        )
        assert r.hypothetical_count >= 1

    def test_for_the_sake_of_argument(self):
        r = measure_exemplification(
            "For the sake of argument, assume perfect information."
        )
        assert r.hypothetical_count >= 1

    def test_hypothetical_diversity(self):
        text = (
            "Imagine a world without borders. "
            "Suppose every person spoke the same language. "
            "Picture the resulting cultural exchange."
        )
        r = measure_exemplification(text)
        assert r.hypothetical_diversity > 0.1


# ── named instances ─────────────────────────────────────────────


class TestNamedInstances:
    def test_proper_noun_multiword(self):
        r = measure_exemplification(
            "Shakespeare wrote Hamlet during the reign of James I."
        )
        assert r.named_instance_count >= 1

    def test_specific_year(self):
        r = measure_exemplification(
            "The Berlin Wall fell in 1989."
        )
        assert r.named_instance_count >= 1

    def test_percentage(self):
        r = measure_exemplification(
            "Unemployment reached 12% during the recession."
        )
        assert r.named_instance_count >= 1

    def test_currency_amount(self):
        r = measure_exemplification(
            "The project cost $4.2 million."
        )
        assert r.named_instance_count >= 1

    def test_multiple_named_instances(self):
        text = (
            "In 2020, the global economy contracted by 3.1%. "
            "The United States spent $5 trillion on relief. "
            "Apple Inc. gained 80% in stock value."
        )
        r = measure_exemplification(text)
        assert r.named_instance_count >= 4

    def test_named_instance_rate(self):
        text = (
            "Marie Curie discovered radium in 1898. "
            "Albert Einstein published relativity in 1905. "
            "Charles Darwin sailed on the Beagle in 1831."
        )
        r = measure_exemplification(text)
        assert r.named_instance_rate > 0


# ── analogical exemplification ──────────────────────────────────


class TestAnalogicalExemplification:
    def test_similarly(self):
        r = measure_exemplification(
            "Bees communicate through dance. "
            "Similarly, ants use chemical trails."
        )
        assert r.analogical_count >= 1

    def test_likewise(self):
        r = measure_exemplification(
            "The heart pumps blood. "
            "Likewise, a water pump moves fluid through pipes."
        )
        assert r.analogical_count >= 1

    def test_just_as(self):
        r = measure_exemplification(
            "Just as a chef balances flavors, a writer balances sentences."
        )
        assert r.analogical_count >= 1

    def test_in_the_same_way(self):
        r = measure_exemplification(
            "In the same way that rivers carve canyons, "
            "persistent habits shape character."
        )
        assert r.analogical_count >= 1

    def test_analogous_to(self):
        r = measure_exemplification(
            "The immune system is analogous to a security network."
        )
        assert r.analogical_count >= 1

    def test_think_of_it_as(self):
        r = measure_exemplification(
            "Think of it as a ladder: each rung builds on the last."
        )
        assert r.analogical_count >= 1

    def test_analogical_diversity(self):
        text = (
            "Similarly, both dolphins and bats use echolocation. "
            "Likewise, octopus intelligence parallels mammalian cognition. "
            "Just as roots anchor a tree, foundations anchor a building."
        )
        r = measure_exemplification(text)
        assert r.analogical_diversity > 0.1


# ── contrastive exemplification ─────────────────────────────────


class TestContrastiveExemplification:
    def test_unlike(self):
        r = measure_exemplification(
            "Unlike mammals, birds lay eggs."
        )
        assert r.contrastive_count >= 1

    def test_in_contrast_to(self):
        r = measure_exemplification(
            "In contrast to classical physics, quantum mechanics allows "
            "superposition."
        )
        assert r.contrastive_count >= 1

    def test_as_opposed_to(self):
        r = measure_exemplification(
            "Use recursion as opposed to iteration for tree traversal."
        )
        assert r.contrastive_count >= 1

    def test_by_contrast(self):
        r = measure_exemplification(
            "The north is densely populated. "
            "By contrast, the south remains largely rural."
        )
        assert r.contrastive_count >= 1

    def test_conversely(self):
        r = measure_exemplification(
            "High prices reduce demand. "
            "Conversely, scarcity increases perceived value."
        )
        assert r.contrastive_count >= 1

    def test_rather_than(self):
        r = measure_exemplification(
            "She chose walking rather than driving."
        )
        assert r.contrastive_count >= 1

    def test_instead_of(self):
        r = measure_exemplification(
            "Use honey instead of sugar in this recipe."
        )
        assert r.contrastive_count >= 1

    def test_contrastive_diversity(self):
        text = (
            "Unlike Python, C requires manual memory management. "
            "By contrast, Java uses garbage collection. "
            "Rather than compiling ahead of time, JavaScript interprets."
        )
        r = measure_exemplification(text)
        assert r.contrastive_diversity > 0.1


# ── composite & classification ──────────────────────────────────


class TestCompositeAndClassification:
    def test_barren_index(self):
        text = "The sky is blue. Water is wet. Fire burns."
        r = measure_exemplification(text)
        assert r.exemplification_index < 0.15

    def test_rich_text(self):
        text = (
            "Many programming languages support object orientation. "
            "For example, Java uses classes and interfaces. "
            "Similarly, Python uses duck typing. "
            "Unlike C, which has no native OOP, modern languages embrace it. "
            "Consider the case of Ruby, designed entirely around objects. "
            "In 2023, GitHub reported 100 million repositories. "
            "Imagine a language without inheritance. "
            "Such as prototype-based JavaScript."
        )
        r = measure_exemplification(text)
        assert r.exemplification_index >= 0.25
        assert r.classification in ("moderate", "rich", "saturated")

    def test_saturated_text(self):
        text = (
            "For example, consider neural networks. "
            "Such as convolutional networks for images. "
            "For instance, ResNet uses skip connections. "
            "Similarly, transformers use self-attention. "
            "Unlike RNNs, transformers process in parallel. "
            "To illustrate, BERT processes bidirectionally. "
            "Imagine a model that scales to 1 trillion parameters. "
            "In 2023, GPT-4 achieved human-level performance. "
            "Suppose we double the training data. "
            "Just as Moore's Law predicted exponential growth. "
            "A case in point is the scaling law of Kaplan et al. "
            "Namely, loss decreases predictably with compute."
        )
        r = measure_exemplification(text)
        assert r.exemplification_index >= 0.45

    def test_index_bounded_zero_one(self):
        text = "For example, for instance, such as, e.g., namely, to wit."
        r = measure_exemplification(text)
        assert 0.0 <= r.exemplification_index <= 1.0

    def test_classification_values(self):
        valid = {"barren", "sparse", "moderate", "rich", "saturated"}
        r = measure_exemplification("Some text with examples such as this.")
        assert r.classification in valid


# ── orthogonality ───────────────────────────────────────────────


class TestOrthogonality:
    def test_high_specificity_low_exemplification(self):
        """A text can be precise without using examples."""
        text = (
            "The Boeing 737 MAX 8 has a wingspan of 35.9 meters. "
            "Its maximum takeoff weight is 82191 kilograms. "
            "The CFM LEAP-1B engines produce 130 kilonewtons of thrust."
        )
        r = measure_exemplification(text)
        # Specific but not exemplifying (no markers, just facts)
        assert r.explicit_count == 0

    def test_high_verbosity_low_exemplification(self):
        """Verbose padding doesn't constitute exemplification."""
        text = (
            "It is important to note that the implementation process "
            "involves a number of different considerations. "
            "In order to achieve optimal results, it should be noted "
            "that various factors must be taken into account."
        )
        r = measure_exemplification(text)
        assert r.exemplification_index < 0.25

    def test_high_exemplification_low_verbosity(self):
        """Examples can be delivered concisely."""
        text = (
            "Sorting algorithms vary. "
            "Quicksort averages O(n log n). "
            "Bubble sort hits O(n²). "
            "Unlike mergesort, quicksort sorts in-place."
        )
        r = measure_exemplification(text)
        assert r.exemplification_index > 0.0


# ── metadata ────────────────────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        r = measure_exemplification(
            "First sentence. Second sentence. Third sentence."
        )
        assert r.total_sentences == 3

    def test_word_count(self):
        r = measure_exemplification(
            "The quick brown fox jumps over the lazy dog."
        )
        assert r.total_words >= 9

    def test_details_dict(self):
        r = measure_exemplification(
            "For example, this text has details."
        )
        assert "exemplification_index" in r.details
        assert "classification" in r.details
        assert "explicit_rate" in r.details


# ── rate calculations ───────────────────────────────────────────


class TestRateCalculations:
    def test_explicit_rate_scaling(self):
        """Rate should scale with sentence count."""
        text = "For example, this is one. " * 10
        r = measure_exemplification(text)
        assert r.explicit_rate > 0

    def test_named_rate_scaling(self):
        text = (
            "Marie Curie won two Nobel Prizes. "
            "Albert Einstein changed physics. "
            "In 1905, relativity emerged."
        )
        r = measure_exemplification(text)
        assert r.named_instance_rate > 0

    def test_single_sentence_high_rate(self):
        """One example in one sentence should yield high rate."""
        r = measure_exemplification(
            "For example, the quick brown fox."
        )
        assert r.explicit_rate >= 100.0


# ── genre patterns ──────────────────────────────────────────────


class TestGenrePatterns:
    def test_textbook_style(self):
        """Textbooks use many examples."""
        text = (
            "Photosynthesis converts light to energy. "
            "For example, oak trees absorb red and blue wavelengths. "
            "Similarly, algae use chlorophyll-a. "
            "Unlike animals, plants produce their own food. "
            "Consider the case of deep-sea organisms that use chemosynthesis."
        )
        r = measure_exemplification(text)
        assert r.exemplification_index >= 0.25

    def test_legal_style(self):
        """Legal prose avoids examples, prefers exhaustive enumeration."""
        text = (
            "The party of the first part shall indemnify the party "
            "of the second part against all claims, demands, and "
            "liabilities arising from the agreement."
        )
        r = measure_exemplification(text)
        assert r.classification in ("barren", "sparse")

    def test_journalism_style(self):
        """Journalism uses named instances heavily."""
        text = (
            "In 2024, the Federal Reserve raised rates by 0.25%. "
            "Jerome Powell cited persistent inflation at 3.4%. "
            "The S&P 500 dropped 2.1% on the announcement. "
            "Apple Inc. and Microsoft Corp. led the decline."
        )
        r = measure_exemplification(text)
        assert r.named_instance_count >= 4


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_same_marker(self):
        """Same marker repeated many times counts each occurrence."""
        text = (
            "For example, cats. "
            "For example, dogs. "
            "For example, birds."
        )
        r = measure_exemplification(text)
        assert r.explicit_count >= 3

    def test_marker_inside_quote(self):
        """Markers inside quotes still count."""
        r = measure_exemplification(
            'The teacher said, "For example, consider gravity."'
        )
        assert r.explicit_count >= 1

    def test_very_long_text(self):
        """Should handle long texts without error."""
        text = "This is a plain sentence. " * 500
        r = measure_exemplification(text)
        assert r.total_sentences == 500
        assert r.classification in ("barren", "sparse")

    def test_mixed_markers_across_channels(self):
        """All channels can fire simultaneously."""
        text = (
            "For example, the 2008 crisis. "
            "Imagine a similar collapse. "
            "Just as the Great Depression reshaped policy. "
            "Unlike previous recessions, this one was global."
        )
        r = measure_exemplification(text)
        assert r.explicit_count >= 1
        assert r.hypothetical_count >= 1
        assert r.analogical_count >= 1
        assert r.contrastive_count >= 1
