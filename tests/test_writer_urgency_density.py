#!/usr/bin/env python3
"""Tests for writer_urgency_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_urgency_density import (
    UrgencyDensityResult,
    measure_urgency_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_urgency_density("")
        assert r.urgency_index == 0.0
        assert r.classification == "unhurried"

    def test_whitespace_only(self):
        r = measure_urgency_density("   \n\n   ")
        assert r.urgency_index == 0.0

    def test_single_word(self):
        r = measure_urgency_density("Hello.")
        assert r.classification == "unhurried"

    def test_no_urgency_plain_sentence(self):
        r = measure_urgency_density("The function returns a boolean value.")
        assert r.total_urgency_markers == 0
        assert r.urgency_index == 0.0


# ── unhurried prose (low urgency density) ───────────────────────


class TestUnhurriedProse:
    def test_plain_factual_no_urgency(self):
        text = (
            "The data was collected over three months. "
            "The sample included 200 participants. "
            "Results were analyzed using standard methods. "
            "The findings are presented in the table below."
        )
        r = measure_urgency_density(text)
        assert r.urgency_index == 0.0
        assert r.classification == "unhurried"

    def test_descriptive_neutral(self):
        text = (
            "The river flows through the valley. "
            "Trees line both banks. "
            "A bridge crosses at the narrowest point. "
            "The path leads to a small village."
        )
        r = measure_urgency_density(text)
        assert r.urgency_index < 0.10

    def test_academic_reference_style(self):
        text = (
            "Smith (2019) examined the relationship between "
            "sleep quality and cognitive performance. "
            "The study employed a within-subjects design. "
            "Participants completed memory tasks across three sessions."
        )
        r = measure_urgency_density(text)
        assert r.classification == "unhurried"
        assert r.total_urgency_markers == 0

    def test_recipe_instructions_calm(self):
        text = (
            "Preheat the oven to 350 degrees. "
            "Mix the flour and sugar in a large bowl. "
            "Add the eggs one at a time. "
            "Bake for 25 to 30 minutes."
        )
        r = measure_urgency_density(text)
        assert r.urgency_index < 0.10


# ── prompting prose (mild urgency) ──────────────────────────────


class TestPromptingProse:
    def test_single_now(self):
        r = measure_urgency_density("You should consider applying now.")
        assert r.temporal_marker_count >= 1
        assert r.urgency_index > 0.0

    def test_mild_deadline(self):
        r = measure_urgency_density(
            "The application deadline is next Friday. "
            "Please submit your materials before then."
        )
        assert r.deadline_count >= 1

    def test_scarcity_hint(self):
        r = measure_urgency_density(
            "This is a limited release. "
            "The design is exclusive to our online store."
        )
        assert r.scarcity_count >= 1

    def test_gentle_consequence(self):
        r = measure_urgency_density(
            "You might want to register soon. "
            "Otherwise you could miss the early bird pricing."
        )
        assert r.consequence_count >= 1

    def test_mild_immediacy(self):
        r = measure_urgency_density(
            "The conference is happening right now. "
            "Speakers are presenting as we speak."
        )
        assert r.immediacy_count >= 1


# ── pressing prose (moderate urgency) ──────────────────────────


class TestPressingProse:
    def test_multiple_channels(self):
        text = (
            "Registration closes at midnight tonight. "
            "Only a few spots remaining. "
            "Do not wait — sign up now or miss out. "
            "Act now to secure your place immediately."
        )
        r = measure_urgency_density(text)
        assert r.urgency_index >= 0.20
        assert r.classification in ("pressing", "urgent", "alarm")

    def test_business_memo_with_deadline(self):
        text = (
            "The proposal deadline is end of day Friday. "
            "Failure to act means your project will not "
            "be considered for funding this quarter. "
            "Please finalize your budgets immediately."
        )
        r = measure_urgency_density(text)
        assert r.deadline_count >= 1
        assert r.consequence_count >= 1

    def test_news_alert_style(self):
        text = (
            "Evacuate immediately — time is running out! "
            "Seek shelter now, right away, without delay!"
        )
        r = measure_urgency_density(text)
        assert r.temporal_marker_count >= 3
        assert r.urgency_index >= 0.10


# ── urgent prose (high urgency) ─────────────────────────────────


class TestUrgentProse:
    def test_heavy_urgency_multi_channel(self):
        text = (
            "Act now — this limited offer expires at midnight tonight! "
            "Don't wait or you will miss out before it is too late! "
            "The clock is ticking, time is running out — grab yours immediately!"
        )
        r = measure_urgency_density(text)
        assert r.urgency_index >= 0.30
        assert r.classification in ("pressing", "urgent", "alarm")
        assert r.total_urgency_markers >= 8

    def test_emergency_broadcast(self):
        text = (
            "Seek shelter immediately — do not wait! "
            "Every second counts, move quickly now!"
        )
        r = measure_urgency_density(text)
        assert r.imperative_count >= 1
        assert r.temporal_marker_count >= 3
        assert r.urgency_index >= 0.10

    def test_sales_closing_pitch(self):
        text = (
            "This is your last chance to get in at this price. "
            "The limited-time offer ends tonight at midnight. "
            "Once it is gone, it is gone — never again. "
            "Don't hesitate — sign up right now. "
            "Don't miss this once-in-a-lifetime opportunity. "
            "Spots are filling up fast — grab yours today!"
        )
        r = measure_urgency_density(text)
        assert r.scarcity_count >= 2
        assert r.deadline_count >= 1
        assert r.total_urgency_markers >= 8


# ── alarm level (extreme urgency) ──────────────────────────────


class TestAlarmLevel:
    def test_maximum_urgency_all_channels(self):
        text = (
            "Act now immediately — this limited offer expires tonight, "
            "don't wait or you will regret it forever! "
            "Only a few left, first come first served — grab yours right now! "
            "The clock is ticking, time is running out — start today without delay! "
            "This is happening as we speak — don't miss this last chance!"
        )
        r = measure_urgency_density(text)
        assert r.urgency_index >= 0.45
        assert r.classification in ("urgent", "alarm")
        assert r.total_urgency_markers >= 15


# ── individual channel tests ────────────────────────────────────


class TestChannelTemporal:
    def test_now_detected(self):
        r = measure_urgency_density("Do it now.")
        assert r.temporal_marker_count >= 1

    def test_immediately_detected(self):
        r = measure_urgency_density("Leave immediately.")
        assert r.temporal_marker_count >= 1

    def test_right_away_phrase(self):
        r = measure_urgency_density("Call them right away.")
        assert r.temporal_marker_count >= 1

    def test_at_once_phrase(self):
        r = measure_urgency_density("Report to the office at once.")
        assert r.temporal_marker_count >= 1

    def test_without_delay_phrase(self):
        r = measure_urgency_density("Begin without delay.")
        assert r.temporal_marker_count >= 1

    def test_time_is_of_the_essence(self):
        r = measure_urgency_density("In this situation, time is of the essence.")
        assert r.temporal_marker_count >= 1

    def test_multiple_temporal_markers(self):
        text = "Now you must act immediately and promptly."
        r = measure_urgency_density(text)
        assert r.temporal_marker_count >= 3


class TestChannelDeadline:
    def test_deadline_word(self):
        r = measure_urgency_density("The deadline is tomorrow.")
        assert r.deadline_count >= 1

    def test_expires(self):
        r = measure_urgency_density("Your subscription expires soon.")
        assert r.deadline_count >= 1

    def test_last_chance(self):
        r = measure_urgency_density("This is your last chance.")
        assert r.deadline_count >= 1

    def test_time_running_out(self):
        r = measure_urgency_density("Time is running out to apply.")
        assert r.deadline_count >= 1

    def test_clock_is_ticking(self):
        r = measure_urgency_density("The clock is ticking on this deal.")
        assert r.deadline_count >= 1

    def test_end_of_day(self):
        r = measure_urgency_density("Submit by end of day.")
        assert r.deadline_count >= 1


class TestChannelScarcity:
    def test_limited_detected(self):
        r = measure_urgency_density("This is a limited edition.")
        assert r.scarcity_count >= 1

    def test_rare_detected(self):
        r = measure_urgency_density("This is a rare opportunity.")
        assert r.scarcity_count >= 1

    def test_once_in_a_lifetime(self):
        r = measure_urgency_density("A once in a lifetime experience.")
        assert r.scarcity_count >= 1

    def test_while_supplies_last(self):
        r = measure_urgency_density("Available while supplies last.")
        assert r.scarcity_count >= 1

    def test_only_a_few(self):
        r = measure_urgency_density("Only a few tickets remain.")
        assert r.scarcity_count >= 1

    def test_fleeting_detected(self):
        r = measure_urgency_density("A fleeting chance to invest.")
        assert r.scarcity_count >= 1


class TestChannelConsequence:
    def test_otherwise(self):
        r = measure_urgency_density("Apply today, otherwise you may be excluded.")
        assert r.consequence_count >= 1

    def test_too_late(self):
        r = measure_urgency_density("Before it is too late, take action.")
        assert r.consequence_count >= 1

    def test_missed_opportunity(self):
        r = measure_urgency_density("This could be a missed opportunity.")
        assert r.consequence_count >= 1

    def test_falling_behind(self):
        r = measure_urgency_density("Competitors are falling behind.")
        # "falling behind" is a phrase match
        assert r.consequence_count >= 1

    def test_failure_to_act(self):
        r = measure_urgency_density("Failure to act will have consequences.")
        assert r.consequence_count >= 2  # phrase + single word

    def test_at_stake(self):
        r = measure_urgency_density("There is a lot at stake here.")
        assert r.consequence_count >= 1


class TestChannelImperative:
    def test_act_now(self):
        r = measure_urgency_density("Act now to save your seat.")
        assert r.imperative_count >= 1

    def test_dont_wait(self):
        r = measure_urgency_density("Don't wait another day.")
        assert r.imperative_count >= 1

    def test_dont_miss(self):
        r = measure_urgency_density("Don't miss this chance.")
        assert r.imperative_count >= 1

    def test_start_today(self):
        r = measure_urgency_density("Start today and see results.")
        assert r.imperative_count >= 1

    def test_seize_the_moment(self):
        r = measure_urgency_density("Seize the moment before it passes.")
        assert r.imperative_count >= 1

    def test_hurry_up(self):
        r = measure_urgency_density("Hurry up and order before they sell out.")
        assert r.imperative_count >= 1


class TestChannelImmediacy:
    def test_is_happening(self):
        r = measure_urgency_density("The sale is happening now.")
        assert r.immediacy_count >= 1

    def test_as_we_speak(self):
        r = measure_urgency_density("Orders are pouring in as we speak.")
        assert r.immediacy_count >= 1

    def test_right_now(self):
        r = measure_urgency_density("You can order right now.")
        assert r.immediacy_count >= 1

    def test_has_just(self):
        r = measure_urgency_density("The price has just dropped.")
        assert r.immediacy_count >= 1

    def test_at_this_moment(self):
        r = measure_urgency_density("At this moment, prices are at their lowest.")
        assert r.immediacy_count >= 1

    def test_already_underway(self):
        r = measure_urgency_density("The event is already underway.")
        assert r.immediacy_count >= 1


# ── classification boundary tests ───────────────────────────────


class TestClassification:
    def test_unhurried_below_010(self):
        text = "The garden has roses and a fountain."
        r = measure_urgency_density(text)
        assert r.classification == "unhurried"
        assert r.urgency_index < 0.10

    def test_alarm_above_045(self):
        text = (
            "Act now immediately — this limited offer expires tonight, "
            "don't wait or you will miss out forever! "
            "The clock is ticking, time is running out, grab yours right now! "
            "Only a few left, first come first served — start today! "
            "This is happening as we speak — don't hesitate, seize the moment!"
        )
        r = measure_urgency_density(text)
        assert r.classification in ("urgent", "alarm")
        assert r.urgency_index >= 0.45


# ── orthogonality tests ─────────────────────────────────────────


class TestOrthogonality:
    def test_urgent_but_not_certain(self):
        """Urgency without certainty — text is urgent but hedges claims."""
        text = (
            "You might want to act now. "
            "This could possibly be your last chance. "
            "It seems like time is running out. "
            "Perhaps you should not wait."
        )
        r = measure_urgency_density(text)
        assert r.urgency_index > 0.10

    def test_certain_but_not_urgent(self):
        """Certainty without urgency — text commits but has no time pressure."""
        text = (
            "The data clearly demonstrates that this approach works. "
            "Every test confirms the hypothesis. "
            "The results are definitively conclusive."
        )
        r = measure_urgency_density(text)
        assert r.urgency_index < 0.10

    def test_urgent_and_verbose(self):
        """Urgency is independent of length."""
        text = (
            "In the extensive and comprehensive history of marketing, "
            "one finds that urgency has been used throughout the ages, "
            "and now, at this very moment, you should act immediately."
        )
        r = measure_urgency_density(text)
        assert r.immediacy_count >= 1


# ── metadata accuracy tests ─────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_urgency_density(text)
        assert r.total_sentences == 3

    def test_word_count(self):
        text = "One two three four five."
        r = measure_urgency_density(text)
        assert r.total_words == 5

    def test_total_markers_sum(self):
        text = (
            "Act now before the deadline expires. "
            "This limited offer is your last chance."
        )
        r = measure_urgency_density(text)
        total = (
            r.temporal_marker_count
            + r.deadline_count
            + r.scarcity_count
            + r.consequence_count
            + r.imperative_count
            + r.immediacy_count
        )
        assert r.total_urgency_markers == total

    def test_index_bounded_zero_to_one(self):
        for text in [
            "",
            "Hello.",
            "Act now immediately! Limited offer expires tonight! Don't wait!",
            "The garden has roses." * 100,
        ]:
            r = measure_urgency_density(text)
            assert 0.0 <= r.urgency_index <= 1.0

    def test_result_is_dataclass(self):
        r = measure_urgency_density("Test.")
        assert isinstance(r, UrgencyDensityResult)


# ── case insensitivity ──────────────────────────────────────────


class TestCaseInsensitivity:
    def test_uppercase_now(self):
        r = measure_urgency_density("NOW is the time to act.")
        assert r.temporal_marker_count >= 1

    def test_uppercase_last_chance(self):
        r = measure_urgency_density("LAST CHANCE to register!")
        assert r.deadline_count >= 1

    def test_mixed_case_act_now(self):
        r = measure_urgency_density("You should Act Now before it ends.")
        assert r.imperative_count >= 1


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence_many_markers(self):
        text = "Act now immediately — this limited offer expires tonight!"
        r = measure_urgency_density(text)
        assert r.total_urgency_markers >= 3
        assert r.urgency_index > 0.0

    def test_repeated_markers(self):
        text = "Now now now now now."
        r = measure_urgency_density(text)
        assert r.temporal_marker_count == 5

    def test_long_text_no_urgency(self):
        text = "The tree stood in the meadow. " * 50
        r = measure_urgency_density(text)
        assert r.urgency_index == 0.0
        assert r.classification == "unhurried"

    def test_newlines_and_special_chars(self):
        text = "Act now!\nDeadline: tomorrow.\nLimited supply!"
        r = measure_urgency_density(text)
        assert r.total_urgency_markers >= 3
