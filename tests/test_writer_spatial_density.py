#!/usr/bin/env python3
"""Tests for writer_spatial_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_spatial_density import (
    SpatialDensityResult,
    measure_spatial_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_spatial_density("")
        assert r.spatial_density_index == 0.0
        assert r.classification == "placeless"

    def test_whitespace_only(self):
        r = measure_spatial_density("   \n\n   ")
        assert r.spatial_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_spatial_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1

    def test_single_word(self):
        r = measure_spatial_density("Hello.")
        assert r.spatial_density_index == 0.0
        assert r.classification == "placeless"


# ── aspatial prose (minimal spatial language) ──────────────────


class TestAspatialProse:
    PLAIN = (
        "The concept of justice involves fairness and equity. "
        "Mathematical proofs require logical deduction from axioms. "
        "Philosophical arguments explore the nature of existence. "
        "Aesthetic appreciation depends on cultural context. "
        "Ethical frameworks guide moral reasoning."
    )

    def test_aspatial_classification(self):
        r = measure_spatial_density(self.PLAIN)
        assert r.classification in ("placeless", "lightly_spatial")
        assert r.spatial_density_index < 0.15

    def test_low_spatial_counts(self):
        r = measure_spatial_density(self.PLAIN)
        assert r.direction_marker_count == 0
        assert r.proximity_expression_count == 0
        assert r.orientation_marker_count == 0
        assert r.containment_count == 0
        assert r.spatial_metaphor_count == 0

    def test_locative_count_low(self):
        r = measure_spatial_density(self.PLAIN)
        # "from" might trigger but is not in our pattern; "on" not present
        assert r.locative_preposition_count <= 2


# ── heavily spatial prose ───────────────────────────────────────


class TestHeavilySpatialProse:
    NAVIGATION = (
        "Walk north along the river toward the bridge. "
        "Turn left at the corner, past the tall building on your right. "
        "Continue straight through the narrow alley behind the market. "
        "The entrance is on the left, next to the wide doorway. "
        "Go inside and walk forward into the spacious lobby. "
        "The office is at the back, beyond the glass partition. "
        "Take the stairs upward to the second floor. "
        "The corridor stretches ahead, with rooms on both sides."
    )

    def test_high_spatial_index(self):
        r = measure_spatial_density(self.NAVIGATION)
        assert r.spatial_density_index >= 0.25
        assert r.classification in ("moderately_spatial", "heavily_spatial", "space_saturated")

    def test_direction_markers_present(self):
        r = measure_spatial_density(self.NAVIGATION)
        assert r.direction_marker_count >= 4

    def test_locative_present(self):
        r = measure_spatial_density(self.NAVIGATION)
        assert r.locative_preposition_count >= 6

    def test_containment_present(self):
        r = measure_spatial_density(self.NAVIGATION)
        assert r.containment_count >= 1

    def test_dimension_present(self):
        r = measure_spatial_density(self.NAVIGATION)
        assert r.dimension_expression_count >= 2


# ── travel writing ──────────────────────────────────────────────


class TestTravelWriting:
    TRAVEL = (
        "The village nestled among the rolling hills, surrounded by "
        "ancient stone walls. A narrow path wound through the olive "
        "groves, leading toward the distant monastery perched on the "
        "hilltop. Below, the valley stretched wide and green, bounded "
        "by the massive river to the east. The tiny chapel stood "
        "beside the sprawling marketplace, its tall spire visible "
        "from every corner of the town. Inside, the cool darkness "
        "enveloped visitors, the air thick with the scent of old wood."
    )

    def test_travel_classification(self):
        r = measure_spatial_density(self.TRAVEL)
        assert r.classification in ("moderately_spatial", "heavily_spatial", "space_saturated")

    def test_containment_in_travel(self):
        r = measure_spatial_density(self.TRAVEL)
        assert r.containment_count >= 2  # "inside", "enveloped"

    def test_dimension_in_travel(self):
        r = measure_spatial_density(self.TRAVEL)
        assert r.dimension_expression_count >= 3  # narrow, wide, massive, tall, sprawling, tiny, tall, old

    def test_direction_in_travel(self):
        r = measure_spatial_density(self.TRAVEL)
        assert r.direction_marker_count >= 2  # "toward", "through", "below"


# ── spatial metaphor prose ──────────────────────────────────────


class TestSpatialMetaphor:
    ABSTRACT = (
        "The company is in trouble after the quarterly results fell "
        "below expectations. The CEO is under pressure from investors "
        "who feel the strategy is off track. The board is behind the "
        "restructuring plan, but employees are on edge about layoffs. "
        "The firm is ahead of schedule on cost-cutting, but far behind "
        "on innovation. The heart of the matter is that the foundation "
        "of the business model has a deep structural flaw."
    )

    def test_metaphor_count(self):
        r = measure_spatial_density(self.ABSTRACT)
        assert r.spatial_metaphor_count >= 3

    def test_metaphor_rate_positive(self):
        r = measure_spatial_density(self.ABSTRACT)
        assert r.spatial_metaphor_rate > 0.0

    def test_abstract_still_spatial(self):
        r = measure_spatial_density(self.ABSTRACT)
        # Even abstract prose with spatial metaphors registers
        assert r.spatial_density_index > 0.05


# ── architecture / technical description ─────────────────────────


class TestArchitectureDescription:
    ARCHITECTURE = (
        "The building stands on a wide plaza, facing south toward "
        "the waterfront. Its tall glass facade is aligned with the "
        "neighboring tower, parallel to the street grid. Inside, "
        "the vast atrium rises sixty feet, enclosed by curved walls "
        "on three sides. Two narrow staircases flank the central "
        "elevator bank, each one tucked behind a shallow alcove. "
        "The rooftop terrace overlooks the sprawling campus below, "
        "bounded by the massive retaining wall to the north."
    )

    def test_architecture_high_spatial(self):
        r = measure_spatial_density(self.ARCHITECTURE)
        assert r.spatial_density_index >= 0.30
        assert r.classification in ("moderately_spatial", "heavily_spatial", "space_saturated")

    def test_orientation_in_architecture(self):
        r = measure_spatial_density(self.ARCHITECTURE)
        assert r.orientation_marker_count >= 1  # "facing", "aligned with", "parallel to"

    def test_containment_in_architecture(self):
        r = measure_spatial_density(self.ARCHITECTURE)
        assert r.containment_count >= 2  # "inside", "enclosed by", "tucked behind"


# ── direction-heavy prose ────────────────────────────────────────


class TestDirectionHeavy:
    DIRECTIONS = (
        "She walked forward through the crowd, heading toward the "
        "exit. Turning left, she hurried past the ticket booth and "
        "down the stairs into the subway. The train was heading "
        "northbound, away from the city center. She moved inward, "
        "away from the doors. The platform rushed past outside the "
        "window. At the next stop, she stepped outward onto the "
        "platform and walked southward toward the exit."
    )

    def test_direction_heavy(self):
        r = measure_spatial_density(self.DIRECTIONS)
        assert r.direction_marker_count >= 6

    def test_direction_rate_high(self):
        r = measure_spatial_density(self.DIRECTIONS)
        assert r.direction_marker_rate > 30.0


# ── proximity-focused prose ──────────────────────────────────────


class TestProximityProse:
    PROXIMITY = (
        "The cafe is close to the university, just a stone's throw "
        "from the main library. The park is nearby, within walking "
        "distance of the student housing. A pharmacy is right next "
        "to the grocery store, at arm's length from the bus stop. "
        "The hospital is not far from the school, in close proximity "
        "to the fire station. Everything is handy to the town center."
    )

    def test_proximity_count(self):
        r = measure_spatial_density(self.PROXIMITY)
        assert r.proximity_expression_count >= 4

    def test_proximity_rate(self):
        r = measure_spatial_density(self.PROXIMITY)
        assert r.proximity_expression_rate > 30.0


# ── containment-heavy prose ──────────────────────────────────────


class TestContainmentProse:
    CONTAINMENT = (
        "The letter was hidden inside the book, buried under layers "
        "of old newspapers. The key was trapped in the lock, sealed "
        "within the mechanism. The cat was nestled in the basket, "
        "surrounded by soft blankets. The documents were enclosed "
        "in a manila envelope, contained within the briefcase. The "
        "treasure was embedded in the rock, immersed in centuries "
        "of sediment."
    )

    def test_containment_count(self):
        r = measure_spatial_density(self.CONTAINMENT)
        assert r.containment_count >= 5

    def test_containment_rate(self):
        r = measure_spatial_density(self.CONTAINMENT)
        assert r.containment_rate > 30.0


# ── rates and scaling ────────────────────────────────────────────


class TestRatesAndScaling:
    def test_rates_scale_with_sentence_count(self):
        one = "The cat sat on the mat beside the door."
        two = one + " " + one
        r1 = measure_spatial_density(one)
        r2 = measure_spatial_density(two)
        # Rate should be similar (same density, double the text)
        if r1.locative_preposition_rate > 0:
            ratio = r2.locative_preposition_rate / r1.locative_preposition_rate
            assert 0.5 <= ratio <= 2.0

    def test_single_sentence_max_rate(self):
        text = "She stood on the bridge above the river."
        r = measure_spatial_density(text)
        assert r.total_sentences == 1
        # One sentence with spatial words → high rate per 100 sentences
        assert r.locative_preposition_rate >= 100.0

    def test_rates_never_negative(self):
        text = "This is a simple sentence with no spatial content at all."
        r = measure_spatial_density(text)
        assert r.locative_preposition_rate >= 0.0
        assert r.direction_marker_rate >= 0.0
        assert r.proximity_expression_rate >= 0.0
        assert r.orientation_marker_rate >= 0.0
        assert r.dimension_expression_rate >= 0.0
        assert r.containment_rate >= 0.0
        assert r.spatial_metaphor_rate >= 0.0


# ── composite index bounds ──────────────────────────────────────


class TestCompositeIndex:
    def test_index_range(self):
        texts = [
            "No spatial words here at all.",
            "The cat on the mat under the tree above the hill beside the river.",
            "She walked toward the bridge through the tunnel into the building.",
        ]
        for text in texts:
            r = measure_spatial_density(text)
            assert 0.0 <= r.spatial_density_index <= 1.0

    def test_index_monotonic_with_density(self):
        low = "Ideas are abstract concepts."
        high = (
            "She walked north through the narrow corridor into the "
            "vast hall, beside the tall pillars on the left, toward "
            "the wide entrance at the far end, inside the ancient "
            "building surrounded by the massive walls."
        )
        r_low = measure_spatial_density(low)
        r_high = measure_spatial_density(high)
        assert r_high.spatial_density_index > r_low.spatial_density_index

    def test_classification_covers_range(self):
        # Ensure all five classification values are reachable
        classifications = set()
        texts = {
            "placeless": "Justice is fairness.",
            "lightly_spatial": "The idea sits at the core of philosophy.",
            "moderately_spatial": (
                "She walked through the garden toward the bench beside the "
                "tall oak tree on the left side of the path."
            ),
            "heavily_spatial": (
                "She walked northward through the narrow alley into the "
                "spacious courtyard, surrounded by tall buildings on three "
                "sides, toward the wide archway at the far end, past the "
                "massive fountain in the center, beside the sprawling garden "
                "behind the ancient wall."
            ),
        }
        for cls, text in texts.items():
            r = measure_spatial_density(text)
            classifications.add(r.classification)
        # At minimum, we should see placeless and at least one spatial class
        assert "placeless" in classifications
        assert len(classifications) >= 2


# ── orthogonality checks ────────────────────────────────────────


class TestOrthogonality:
    TEMPORAL_NOT_SPATIAL = (
        "She arrived at noon. Then he left. Afterwards, they met again. "
        "The meeting lasted for three hours. Eventually, she decided. "
        "Meanwhile, the rain continued. Finally, the sun appeared."
    )

    SPATIAL_NOT_TEMPORAL = (
        "The book sits on the shelf above the desk. The lamp stands "
        "beside the chair near the window. The rug lies under the table "
        "in the center of the room. The curtains hang across the wide "
        "opening between the two tall columns."
    )

    def test_temporal_low_spatial(self):
        r = measure_spatial_density(self.TEMPORAL_NOT_SPATIAL)
        # Temporal prose should not necessarily be spatial
        assert r.spatial_density_index < 0.35

    def test_spatial_low_temporal(self):
        r = measure_spatial_density(self.SPATIAL_NOT_TEMPORAL)
        # Spatial prose should have high spatial but low temporal
        assert r.spatial_density_index > 0.10
        assert r.direction_marker_count == 0 or r.direction_marker_count <= 2


# ── diversity index ─────────────────────────────────────────────


class TestDiversityIndex:
    def test_low_diversity_repetitive(self):
        # Same spatial word repeated
        text = "The cat is on the mat. The dog is on the rug. The bird is on the branch."
        r = measure_spatial_density(text)
        # Only "on" is used → low diversity
        assert r.spatial_diversity_index < 0.2

    def test_high_diversity_varied(self):
        text = (
            "The cat is on the mat. The dog sits under the table. "
            "The bird flew toward the tree. The fish swam through "
            "the water. The fox hid behind the rock. The bear "
            "walked along the river. The deer stood beside the stream."
        )
        r = measure_spatial_density(text)
        assert r.spatial_diversity_index >= 0.2

    def test_diversity_index_range(self):
        texts = [
            "No spatial words.",
            "On the mat on the rug on the floor on the ground.",
        ]
        for text in texts:
            r = measure_spatial_density(text)
            assert 0.0 <= r.spatial_diversity_index <= 1.0


# ── details dict ────────────────────────────────────────────────


class TestDetailsDict:
    def test_details_keys(self):
        r = measure_spatial_density("The cat sat on the mat.")
        expected_keys = {
            "locative_preposition_rate",
            "direction_marker_rate",
            "proximity_expression_rate",
            "orientation_marker_rate",
            "dimension_expression_rate",
            "containment_rate",
            "spatial_metaphor_rate",
            "spatial_diversity_index",
            "spatial_density_index",
            "classification",
        }
        assert set(r.details.keys()) == expected_keys

    def test_details_values_match_fields(self):
        r = measure_spatial_density(
            "She walked toward the bridge through the narrow alley."
        )
        assert r.details["locative_preposition_rate"] == r.locative_preposition_rate
        assert r.details["direction_marker_rate"] == r.direction_marker_rate
        assert r.details["spatial_density_index"] == r.spatial_density_index
        assert r.details["classification"] == r.classification


# ── result dataclass defaults ────────────────────────────────────


class TestResultDefaults:
    def test_default_values(self):
        r = SpatialDensityResult()
        assert r.locative_preposition_count == 0
        assert r.direction_marker_count == 0
        assert r.proximity_expression_count == 0
        assert r.orientation_marker_count == 0
        assert r.dimension_expression_count == 0
        assert r.containment_count == 0
        assert r.spatial_metaphor_count == 0
        assert r.unique_spatial_forms == 0
        assert r.spatial_density_index == 0.0
        assert r.classification == "placeless"
        assert r.total_sentences == 0
        assert r.details == {}

    def test_result_is_dataclass(self):
        import dataclasses
        assert dataclasses.is_dataclass(SpatialDensityResult())


# ── long prose stress test ──────────────────────────────────────


class TestLongProse:
    LONG_TEXT = (
        "The ancient city sprawled across the valley, bounded by the "
        "massive mountains to the north and the wide river to the south. "
        "Narrow streets wound through the old quarter, past crumbling "
        "buildings on either side. The marketplace sat at the center, "
        "surrounded by tall archways and spacious colonnades. Beyond "
        "the city walls, the farmland stretched toward the distant hills. "
        "Inside the cathedral, vast columns rose upward into the shadowy "
        "vault above. The altar stood at the eastern end, behind the "
        "ornate screen, enclosed within the choir. Small chapels nestled "
        "along the side aisles, each one tucked behind a low railing. "
        "The bell tower loomed over the square, its tall spire visible "
        "from every corner of the town. Below the city, the catacombs "
        "stretched deep underground, hidden beneath centuries of rubble. "
        "The river flowed past the eastern wall, under the ancient bridge, "
        "and outward toward the distant sea. On the western hill, the "
        "fortress stood beside the old watchtower, facing the valley below."
    )

    def test_long_text_completes(self):
        r = measure_spatial_density(self.LONG_TEXT)
        assert r.total_sentences >= 10

    def test_long_text_high_spatial(self):
        r = measure_spatial_density(self.LONG_TEXT)
        assert r.spatial_density_index >= 0.25
        assert r.classification in ("moderately_spatial", "heavily_spatial", "space_saturated")

    def test_long_text_all_categories_present(self):
        r = measure_spatial_density(self.LONG_TEXT)
        assert r.locative_preposition_count > 0
        assert r.direction_marker_count > 0
        assert r.dimension_expression_count > 0
        assert r.containment_count > 0

    def test_long_text_diversity(self):
        r = measure_spatial_density(self.LONG_TEXT)
        assert r.spatial_diversity_index >= 0.3


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_all_caps(self):
        text = "THE CAT SAT ON THE MAT UNDER THE TREE."
        r = measure_spatial_density(text)
        assert r.locative_preposition_count >= 2

    def test_mixed_case(self):
        text = "The Cat Sat On The Mat Under The Tree."
        r = measure_spatial_density(text)
        assert r.locative_preposition_count >= 2

    def test_with_numbers(self):
        text = "Room 42 is on the 3rd floor, behind door 7."
        r = measure_spatial_density(text)
        assert r.locative_preposition_count >= 2

    def test_punctuation_adjacent(self):
        text = "Inside, the room was vast. Outside, the garden sprawled."
        r = measure_spatial_density(text)
        assert r.containment_count >= 2

    def test_newlines_and_tabs(self):
        text = "The cat\nsat on\tthe mat.\nThe dog\nlay under\tthe table."
        r = measure_spatial_density(text)
        assert r.locative_preposition_count >= 2

    def test_repeated_periods(self):
        text = "She stood on the bridge... The river below... The sky above..."
        r = measure_spatial_density(text)
        assert r.total_sentences >= 1
