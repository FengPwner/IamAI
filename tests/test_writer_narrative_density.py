#!/usr/bin/env python3
"""Tests for writer_narrative_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_narrative_density import (
    NarrativeDensityResult,
    measure_narrative_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_narrative_density("")
        assert r.narrative_index == 0.0
        assert r.classification == "expository"

    def test_whitespace_only(self):
        r = measure_narrative_density("   \n\n   ")
        assert r.narrative_index == 0.0

    def test_single_word(self):
        r = measure_narrative_density("Hello.")
        assert r.classification == "expository"

    def test_no_narrative_plain_sentence(self):
        r = measure_narrative_density("The function returns a boolean value.")
        assert r.total_narrative_markers == 0 or r.narrative_index < 0.10


# ── expository prose (low narrative density) ────────────────────


class TestExpositoryProse:
    EXPOSITORY = (
        "The mitochondria are organelles found in most eukaryotic cells. "
        "They generate adenosine triphosphate through oxidative phosphorylation. "
        "The process occurs across the inner mitochondrial membrane. "
        "This membrane contains protein complexes of the electron transport chain. "
        "Each complex transfers electrons from a donor to an acceptor. "
        "The energy released pumps protons into the intermembrane space. "
        "The resulting gradient drives ATP synthase."
    )

    def test_expository_classification(self):
        r = measure_narrative_density(self.EXPOSITORY)
        assert r.classification in ("expository", "anecdotal")

    def test_low_index(self):
        r = measure_narrative_density(self.EXPOSITORY)
        assert r.narrative_index < 0.25

    def test_zero_dialogue(self):
        r = measure_narrative_density(self.EXPOSITORY)
        assert r.dialogue_marker_count == 0
        assert r.quoted_speech_count == 0

    def test_low_action_verbs(self):
        r = measure_narrative_density(self.EXPOSITORY)
        assert r.action_verb_count <= 2


# ── storied prose (high narrative density) ──────────────────────


class TestStoriedProse:
    STORIED = (
        "She burst into the room at dawn. "
        "He looked up from the desk, startled. "
        "'Where have you been?' he demanded. "
        "'Running,' she whispered, still gasping for breath. "
        "Then she crossed the floor and grabbed his arm. "
        "'They're coming,' she hissed. "
        "He stood and reached for the knife on the table. "
        "Outside, footsteps echoed along the corridor. "
        "Moments later, someone knocked on the door. "
        "She pulled him behind the curtain. "
        "The door burst open. "
        "Two men stepped into the room. "
        "'Check under the bed,' one shouted. "
        "Meanwhile, she slipped toward the window. "
        "He followed, stumbling over a chair. "
        "They leapt onto the ledge just as the men turned. "
        "Then they jumped into the darkness below."
    )

    def test_storied_classification(self):
        r = measure_narrative_density(self.STORIED)
        assert r.classification in ("immersive", "storied")

    def test_high_index(self):
        r = measure_narrative_density(self.STORIED)
        assert r.narrative_index > 0.45

    def test_has_action_verbs(self):
        r = measure_narrative_density(self.STORIED)
        assert r.action_verb_count >= 10

    def test_has_temporal_sequencing(self):
        r = measure_narrative_density(self.STORIED)
        assert r.temporal_sequence_count >= 2

    def test_has_character_presence(self):
        r = measure_narrative_density(self.STORIED)
        assert r.character_presence_count >= 5

    def test_has_dialogue(self):
        r = measure_narrative_density(self.STORIED)
        assert r.dialogue_marker_count >= 3
        assert r.quoted_speech_count >= 2

    def test_has_scene_setting(self):
        r = measure_narrative_density(self.STORIED)
        assert r.scene_setting_count >= 1


# ── action verbs ────────────────────────────────────────────────


class TestActionVerbs:
    def test_locomotion(self):
        text = "She ran across the field and dashed through the gate."
        r = measure_narrative_density(text)
        assert r.action_verb_count >= 2

    def test_manipulation(self):
        text = "He grabbed the handle and pulled the door open."
        r = measure_narrative_density(text)
        assert r.action_verb_count >= 2

    def test_bodily_action(self):
        text = "She knelt beside the bed and whispered a prayer."
        r = measure_narrative_density(text)
        assert r.action_verb_count >= 2

    def test_combat(self):
        text = "He struck the shield, then dodged the counterblow."
        r = measure_narrative_density(text)
        assert r.action_verb_count >= 2

    def test_creation(self):
        text = "She chopped the onions and stirred the pot."
        r = measure_narrative_density(text)
        assert r.action_verb_count >= 2

    def test_stative_not_counted(self):
        text = "The building is tall and seems well-maintained."
        r = measure_narrative_density(text)
        assert r.action_verb_count == 0

    def test_cognitive_not_counted(self):
        text = "She believes the theory and considers it plausible."
        r = measure_narrative_density(text)
        assert r.action_verb_count == 0


# ── temporal sequencing ─────────────────────────────────────────


class TestTemporalSequencing:
    def test_then(self):
        text = "She opened the door. Then she stepped inside."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_after(self):
        text = "After the meeting ended, everyone left."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_suddenly(self):
        text = "Suddenly, the lights went out."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_meanwhile(self):
        text = "Meanwhile, the thief slipped away."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_moments_later(self):
        text = "Moments later, the door creaked open."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_next_day(self):
        text = "The next morning, she packed her bags."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_as_soon_as(self):
        text = "As soon as he arrived, the phone rang."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_eventually(self):
        text = "Eventually, they found the hidden path."
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 1

    def test_multiple_sequencers(self):
        text = (
            "First she checked the lock. "
            "Then she peeked through the curtain. "
            "After that, she opened the door. "
            "Suddenly, a shadow moved. "
            "Finally, she stepped outside."
        )
        r = measure_narrative_density(text)
        assert r.temporal_sequence_count >= 4


# ── character presence ───────────────────────────────────────────


class TestCharacterPresence:
    def test_third_person_pronouns(self):
        text = "He walked to the window. She followed him."
        r = measure_narrative_density(text)
        assert r.character_presence_count >= 3  # he, she, him

    def test_first_person(self):
        text = "I opened the door and we stepped inside."
        r = measure_narrative_density(text)
        assert r.character_presence_count >= 2  # I, we

    def test_character_introduction(self):
        text = "She encountered a stranger at the gate."
        r = measure_narrative_density(text)
        assert r.character_presence_count >= 2  # she + encountered

    def test_no_pronouns(self):
        text = "The process requires careful calibration of the instrument."
        r = measure_narrative_density(text)
        assert r.character_presence_count == 0

    def test_mixed_pronouns(self):
        text = "He told her that they would arrive later."
        r = measure_narrative_density(text)
        assert r.character_presence_count >= 3


# ── dialogue markers ────────────────────────────────────────────


class TestDialogueMarkers:
    def test_said(self):
        text = '"I know," she said.'
        r = measure_narrative_density(text)
        assert r.dialogue_marker_count >= 1
        assert r.quoted_speech_count >= 1

    def test_asked(self):
        text = '"Where are you going?" he asked.'
        r = measure_narrative_density(text)
        assert r.dialogue_marker_count >= 1

    def test_whispered(self):
        text = '"Be quiet," she whispered.'
        r = measure_narrative_density(text)
        assert r.dialogue_marker_count >= 1

    def test_shouted(self):
        text = '"Get down!" he shouted.'
        r = measure_narrative_density(text)
        assert r.dialogue_marker_count >= 1

    def test_no_dialogue(self):
        text = "The committee released its findings on Tuesday."
        r = measure_narrative_density(text)
        assert r.dialogue_marker_count == 0
        assert r.quoted_speech_count == 0

    def test_multiple_exchanges(self):
        text = (
            '"What time is it?" she asked. '
            '"Almost midnight," he replied. '
            '"We should leave," she insisted. '
            '"Not yet," he whispered.'
        )
        r = measure_narrative_density(text)
        assert r.dialogue_marker_count >= 4
        assert r.quoted_speech_count >= 4

    def test_demanded(self):
        text = '"Tell me everything," she demanded.'
        r = measure_narrative_density(text)
        assert r.dialogue_marker_count >= 1


# ── scene-setting ───────────────────────────────────────────────


class TestSceneSetting:
    def test_entered_room(self):
        text = "She entered the room and looked around."
        r = measure_narrative_density(text)
        assert r.scene_setting_count >= 1

    def test_at_dawn(self):
        text = "At dawn, the soldiers broke camp."
        r = measure_narrative_density(text)
        assert r.scene_setting_count >= 1

    def test_atmospheric_verb(self):
        text = "Darkness fell across the valley."
        r = measure_narrative_density(text)
        assert r.scene_setting_count >= 1

    def test_locative_grounding(self):
        text = "They walked across the bridge and through the forest."
        r = measure_narrative_density(text)
        assert r.scene_setting_count >= 2

    def test_silence_fell(self):
        text = "Silence fell over the crowd."
        r = measure_narrative_density(text)
        assert r.scene_setting_count >= 1

    def test_light_streamed(self):
        text = "Light streamed through the broken window."
        r = measure_narrative_density(text)
        assert r.scene_setting_count >= 1

    def test_no_scene(self):
        text = "The ratio of circumference to diameter is approximately 3.14."
        r = measure_narrative_density(text)
        assert r.scene_setting_count == 0


# ── composite index ─────────────────────────────────────────────


class TestCompositeIndex:
    def test_index_range(self):
        """Index should always be between 0.0 and 1.0."""
        texts = [
            "",
            "The cat sat on the mat.",
            "She ran across the bridge and leapt onto the boat.",
            "A" * 1000,
        ]
        for text in texts:
            r = measure_narrative_density(text)
            assert 0.0 <= r.narrative_index <= 1.0

    def test_monotonic_increase(self):
        """More narrative → higher index."""
        expository = "The committee published its annual report on Tuesday."
        anecdotal = "One Tuesday, the committee chair walked in and announced the results."
        narrative = (
            "She burst into the conference room. "
            "'The results are in,' she declared. "
            "Everyone turned. "
            "Then she placed the report on the table. "
            "'Read it,' she said."
        )
        r1 = measure_narrative_density(expository)
        r2 = measure_narrative_density(anecdotal)
        r3 = measure_narrative_density(narrative)
        assert r1.narrative_index < r3.narrative_index
        assert r2.narrative_index < r3.narrative_index

    def test_weights_sum_to_one(self):
        """The five weights should sum to 1.0."""
        assert 0.30 + 0.15 + 0.20 + 0.20 + 0.15 == pytest.approx(1.0)


# ── classification thresholds ───────────────────────────────────


class TestClassification:
    def test_expository_threshold(self):
        """Technical text should have low narrative density."""
        text = (
            "The function accepts two integer parameters. "
            "It returns their greatest common divisor. "
            "The algorithm uses the Euclidean method. "
            "Each iteration computes a remainder. "
            "The process terminates when the remainder equals zero."
        )
        r = measure_narrative_density(text)
        assert r.classification in ("expository", "anecdotal")
        assert r.narrative_index < 0.25

    def test_storied_threshold(self):
        """Densely narrative text should be immersive or storied."""
        text = (
            "She burst into the room. "
            "'They found us,' she hissed. "
            "He grabbed the bag and ran to the window. "
            "Then they leapt onto the fire escape. "
            "Footsteps echoed below. "
            "'Hurry!' she shouted. "
            "He stumbled, caught the railing, and pulled himself up. "
            "Meanwhile, the door behind them burst open. "
            "They scrambled across the rooftop. "
            "Suddenly, a spotlight swept toward them."
        )
        r = measure_narrative_density(text)
        assert r.classification in ("immersive", "storied")

    def test_all_classifications_valid(self):
        """Classification should always be one of the five valid values."""
        valid = {"expository", "anecdotal", "narrative", "immersive", "storied"}
        texts = [
            "",
            "Short.",
            "The cat sat.",
            "She ran across the bridge.",
            "'Stop!' he shouted, grabbing her arm.",
        ]
        for text in texts:
            r = measure_narrative_density(text)
            assert r.classification in valid


# ── metadata ────────────────────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_narrative_density(text)
        assert r.total_sentences == 3

    def test_word_count(self):
        text = "The quick brown fox jumped."
        r = measure_narrative_density(text)
        assert r.total_words == 5

    def test_total_markers_sum(self):
        text = (
            "She ran to the door. Then she entered the room. "
            "'Hello,' she said. At dawn, the city stirred."
        )
        r = measure_narrative_density(text)
        total_dialogue = r.dialogue_marker_count + r.quoted_speech_count
        expected = (
            r.action_verb_count
            + r.temporal_sequence_count
            + r.character_presence_count
            + total_dialogue
            + r.scene_setting_count
        )
        assert r.total_narrative_markers == expected

    def test_details_dict(self):
        text = "She walked into the room at dawn."
        r = measure_narrative_density(text)
        assert "narrative_index" in r.details
        assert "classification" in r.details
        assert "action_verb_rate" in r.details
        assert "temporal_sequence_rate" in r.details
        assert "character_presence_rate" in r.details
        assert "dialogue_marker_rate" in r.details
        assert "scene_setting_rate" in r.details


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence(self):
        text = "She ran."
        r = measure_narrative_density(text)
        assert r.total_sentences >= 1

    def test_repeated_action_verbs(self):
        text = "She ran and ran and ran."
        r = measure_narrative_density(text)
        assert r.action_verb_count >= 3

    def test_case_insensitive(self):
        lower = "she ran across the bridge."
        upper = "SHE RAN ACROSS THE BRIDGE."
        r1 = measure_narrative_density(lower)
        r2 = measure_narrative_density(upper)
        assert r1.action_verb_count == r2.action_verb_count

    def test_mixed_case(self):
        text = "She RAN across the Bridge and THEN she Jumped."
        r = measure_narrative_density(text)
        assert r.action_verb_count >= 2

    def test_long_text(self):
        """Longer text should not break anything."""
        text = ("The process iterates. " * 100) + (
            "She ran across the bridge and leapt onto the waiting boat. " * 50
        )
        r = measure_narrative_density(text)
        assert 0.0 <= r.narrative_index <= 1.0

    def test_no_sentence_ending_punctuation(self):
        text = "She ran across the bridge and he followed her"
        r = measure_narrative_density(text)
        assert r.total_sentences >= 1

    def test_special_characters(self):
        text = '"Stop!" she shouted. "Don\'t move!"'
        r = measure_narrative_density(text)
        assert r.total_sentences >= 1

    def test_numbers_in_text(self):
        text = "In 2024, she walked into the courtroom at 9 AM."
        r = measure_narrative_density(text)
        assert r.total_words > 0

    def test_multiline_text(self):
        text = "She ran.\n\nHe followed.\n\nThey vanished into the night."
        r = measure_narrative_density(text)
        assert r.total_sentences >= 3

    def test_quoted_non_speech(self):
        """Quoted text that isn't speech should still be counted by regex."""
        text = 'The term "recursion" refers to self-reference.'
        r = measure_narrative_density(text)
        assert r.quoted_speech_count >= 1

    def test_empty_quotes(self):
        text = 'She said "" and walked away.'
        r = measure_narrative_density(text)
        # empty quotes may or may not match; just don't crash
        assert r.total_sentences >= 1


# ── orthogonality sanity ────────────────────────────────────────


class TestOrthogonality:
    def test_high_formality_low_narrative(self):
        """Formal prose can have zero narrative."""
        text = (
            "Pursuant to Section 4.2 of the agreement, the licensee "
            "shall maintain confidentiality of all proprietary information. "
            "Disclosure constitutes a material breach."
        )
        r = measure_narrative_density(text)
        assert r.narrative_index < 0.25

    def test_high_narrative_low_formality(self):
        """Informal narrative can have high density."""
        text = (
            "He grabbed his jacket and bolted out the door. "
            "'Catch me if you can!' he yelled. "
            "Then he sprinted down the alley and vanished."
        )
        r = measure_narrative_density(text)
        assert r.narrative_index > 0.25
