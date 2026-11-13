#!/usr/bin/env python3
"""Tests for writer_imperative_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_imperative_density import (  # noqa: E402
    DIRECT_IMPERATIVE_PATTERNS,
    HORTATIVE_PATTERNS,
    INSTRUCTIONAL_PATTERNS,
    NEGATIVE_IMPERATIVE_PATTERNS,
    SOFTENED_IMPERATIVE_PATTERNS,
    WriterImperativeDensity,
    _count_matching,
    _split_sentences,
)


# ── Helpers ──────────────────────────────────────────────────────────


class TestSplitSentences(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   \n  "), [])

    def test_single_sentence(self):
        self.assertEqual(_split_sentences("She walked home."), ["She walked home."])

    def test_multiple_sentences(self):
        result = _split_sentences("He ran. She walked. They stayed.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        result = _split_sentences("Why? How? Where?")
        self.assertEqual(len(result), 3)

    def test_exclamation_marks(self):
        result = _split_sentences("Stop! Wait! Go!")
        self.assertEqual(len(result), 3)

    def test_mixed_punctuation(self):
        result = _split_sentences("Hello. What? Yes! No.")
        self.assertEqual(len(result), 4)

    def test_newlines(self):
        result = _split_sentences("First sentence.\nSecond sentence.")
        self.assertEqual(len(result), 2)

    def test_strips_whitespace(self):
        result = _split_sentences("  Hello world.  ")
        self.assertEqual(result, ["Hello world."])


class TestCountMatching(unittest.TestCase):
    def test_empty_sentences(self):
        self.assertEqual(_count_matching([], DIRECT_IMPERATIVE_PATTERNS), 0)

    def test_no_matches(self):
        sentences = ["The cat sat on the mat.", "She walked home quietly."]
        self.assertEqual(_count_matching(sentences, DIRECT_IMPERATIVE_PATTERNS), 0)

    def test_all_match(self):
        sentences = ["Stop.", "Wait.", "Listen."]
        count = _count_matching(sentences, DIRECT_IMPERATIVE_PATTERNS)
        self.assertGreater(count, 0)

    def test_partial_match(self):
        sentences = ["Stop.", "The cat sat.", "Listen.", "She walked."]
        count = _count_matching(sentences, DIRECT_IMPERATIVE_PATTERNS)
        self.assertGreaterEqual(count, 2)


# ── Direct Imperative Patterns ───────────────────────────────────────


class TestDirectImperativePatterns(unittest.TestCase):
    def test_short_command_stop(self):
        self.assertTrue(any(p.search("Stop.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_wait(self):
        self.assertTrue(any(p.search("Wait.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_listen(self):
        self.assertTrue(any(p.search("Listen.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_look(self):
        self.assertTrue(any(p.search("Look.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_go(self):
        self.assertTrue(any(p.search("Go.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_run(self):
        self.assertTrue(any(p.search("Run.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_come(self):
        self.assertTrue(any(p.search("Come.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_read(self):
        self.assertTrue(any(p.search("Read.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_write(self):
        self.assertTrue(any(p.search("Write.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_think(self):
        self.assertTrue(any(p.search("Think.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_consider(self):
        self.assertTrue(any(p.search("Consider this.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_imagine(self):
        self.assertTrue(any(p.search("Imagine that.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_observe(self):
        self.assertTrue(any(p.search("Observe carefully.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_examine(self):
        self.assertTrue(any(p.search("Examine the data.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_short_command_compare(self):
        self.assertTrue(any(p.search("Compare the results.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_transitive_verb_the_file(self):
        self.assertTrue(any(p.search("Open the file.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_transitive_verb_the_tests(self):
        self.assertTrue(any(p.search("Run the tests.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_transitive_verb_the_documentation(self):
        self.assertTrue(any(p.search("Read the documentation.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_transitive_verb_your_code(self):
        self.assertTrue(any(p.search("Test your code.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_transitive_verb_this_example(self):
        self.assertTrue(any(p.search("Consider this example.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_verb_adverb_carefully(self):
        self.assertTrue(any(p.search("Look carefully.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_verb_adverb_again(self):
        self.assertTrue(any(p.search("Think again.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_verb_adverb_harder(self):
        self.assertTrue(any(p.search("Try harder.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_see_also(self):
        self.assertTrue(any(p.search("See also the appendix.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_see_chapter(self):
        self.assertTrue(any(p.search("See chapter seven.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_see_below(self):
        self.assertTrue(any(p.search("See below for details.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_refer_to(self):
        self.assertTrue(any(p.search("Refer to the documentation.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_not_declarative(self):
        self.assertFalse(any(p.search("The committee reviewed the proposal.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_not_declarative_she_considered(self):
        self.assertFalse(any(p.search("She considered the options.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_not_declarative_they_observed(self):
        self.assertFalse(any(p.search("They observed the phenomenon.") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_exclamation_mark(self):
        self.assertTrue(any(p.search("Stop!") for p in DIRECT_IMPERATIVE_PATTERNS))

    def test_question_mark(self):
        # Imperatives don't usually take question marks
        result = any(p.search("Consider this?") for p in DIRECT_IMPERATIVE_PATTERNS)
        # Either True or False is acceptable — patterns accept [?!.]
        self.assertIsInstance(result, bool)


# ── Softened Imperative Patterns ─────────────────────────────────────


class TestSoftenedImperativePatterns(unittest.TestCase):
    def test_please_consider(self):
        self.assertTrue(any(p.search("Please consider this option.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_please_note(self):
        self.assertTrue(any(p.search("Please note the deadline.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_please_submit(self):
        self.assertTrue(any(p.search("Please submit the form.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_please_review(self):
        self.assertTrue(any(p.search("Please review the changes.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_please_wait(self):
        self.assertTrue(any(p.search("Please wait here.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_kindly_review(self):
        self.assertTrue(any(p.search("Kindly review the attached document.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_kindly_submit(self):
        self.assertTrue(any(p.search("Kindly submit your response.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_do_try(self):
        self.assertTrue(any(p.search("Do try this approach.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_do_consider(self):
        self.assertTrue(any(p.search("Do consider the alternatives.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_do_remember(self):
        self.assertTrue(any(p.search("Do remember the deadline.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_do_let(self):
        self.assertTrue(any(p.search("Do let me know.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_just_run(self):
        self.assertTrue(any(p.search("Just run the tests.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_just_try(self):
        self.assertTrue(any(p.search("Just try again.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_just_look(self):
        self.assertTrue(any(p.search("Just look at the output.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_perhaps_consider(self):
        self.assertTrue(any(p.search("Perhaps consider a different approach.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_maybe_try(self):
        self.assertTrue(any(p.search("Maybe try restarting the service.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_you_might_want_to(self):
        self.assertTrue(any(p.search("You might want to check the logs.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_you_may_want_to(self):
        self.assertTrue(any(p.search("You may want to update the configuration.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_you_might_wish_to(self):
        self.assertTrue(any(p.search("You might wish to review the findings.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_try_to_keep(self):
        self.assertTrue(any(p.search("Try to keep the changes minimal.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_try_running(self):
        self.assertTrue(any(p.search("Try running the diagnostic tool.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_feel_free_to(self):
        self.assertTrue(any(p.search("Feel free to ask questions.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_dont_hesitate_to(self):
        self.assertTrue(any(p.search("Don't hesitate to reach out.") for p in SOFTENED_IMPERATIVE_PATTERNS))

    def test_not_declarative(self):
        self.assertFalse(any(p.search("The weather was beautiful.") for p in SOFTENED_IMPERATIVE_PATTERNS))


# ── Hortative Patterns ───────────────────────────────────────────────


class TestHortativePatterns(unittest.TestCase):
    def test_lets_examine(self):
        self.assertTrue(any(p.search("Let's examine the evidence.") for p in HORTATIVE_PATTERNS))

    def test_lets_try(self):
        self.assertTrue(any(p.search("Let's try a different approach.") for p in HORTATIVE_PATTERNS))

    def test_lets_consider(self):
        self.assertTrue(any(p.search("Let's consider the alternatives.") for p in HORTATIVE_PATTERNS))

    def test_lets_begin(self):
        self.assertTrue(any(p.search("Let's begin the analysis.") for p in HORTATIVE_PATTERNS))

    def test_lets_not_forget(self):
        self.assertTrue(any(p.search("Let's not forget the context.") for p in HORTATIVE_PATTERNS))

    def test_let_us_consider(self):
        self.assertTrue(any(p.search("Let us consider the implications.") for p in HORTATIVE_PATTERNS))

    def test_let_us_examine(self):
        self.assertTrue(any(p.search("Let us examine the data carefully.") for p in HORTATIVE_PATTERNS))

    def test_let_us_not(self):
        self.assertTrue(any(p.search("Let us not be hasty.") for p in HORTATIVE_PATTERNS))

    def test_let_me_show(self):
        self.assertTrue(any(p.search("Let me show you the results.") for p in HORTATIVE_PATTERNS))

    def test_let_me_explain(self):
        self.assertTrue(any(p.search("Let me explain the reasoning.") for p in HORTATIVE_PATTERNS))

    def test_lets_go(self):
        self.assertTrue(any(p.search("Let's go.") for p in HORTATIVE_PATTERNS))

    def test_lets_see(self):
        self.assertTrue(any(p.search("Let's see.") for p in HORTATIVE_PATTERNS))

    def test_shall_we_begin(self):
        self.assertTrue(any(p.search("Shall we begin?") for p in HORTATIVE_PATTERNS))

    def test_shall_we_proceed(self):
        self.assertTrue(any(p.search("Shall we proceed?") for p in HORTATIVE_PATTERNS))

    def test_not_declarative_we_examined(self):
        self.assertFalse(any(p.search("We examined the evidence.") for p in HORTATIVE_PATTERNS))

    def test_not_declarative_they_let(self):
        self.assertFalse(any(p.search("They let the dog out.") for p in HORTATIVE_PATTERNS))


# ── Instructional Patterns ───────────────────────────────────────────


class TestInstructionalPatterns(unittest.TestCase):
    def test_first_open(self):
        self.assertTrue(any(p.search("First, open the terminal.") for p in INSTRUCTIONAL_PATTERNS))

    def test_next_run(self):
        self.assertTrue(any(p.search("Next, run the install command.") for p in INSTRUCTIONAL_PATTERNS))

    def test_then_configure(self):
        self.assertTrue(any(p.search("Then, configure the settings.") for p in INSTRUCTIONAL_PATTERNS))

    def test_finally_restart(self):
        self.assertTrue(any(p.search("Finally, restart the server.") for p in INSTRUCTIONAL_PATTERNS))

    def test_afterwards_check(self):
        self.assertTrue(any(p.search("Afterwards, check the logs.") for p in INSTRUCTIONAL_PATTERNS))

    def test_lastly_verify(self):
        self.assertTrue(any(p.search("Lastly, verify the output.") for p in INSTRUCTIONAL_PATTERNS))

    def test_make_sure_to(self):
        self.assertTrue(any(p.search("Make sure to save your work.") for p in INSTRUCTIONAL_PATTERNS))

    def test_be_sure_to(self):
        self.assertTrue(any(p.search("Be sure to check the output.") for p in INSTRUCTIONAL_PATTERNS))

    def test_remember_to(self):
        self.assertTrue(any(p.search("Remember to set the API key.") for p in INSTRUCTIONAL_PATTERNS))

    def test_dont_forget_to(self):
        self.assertTrue(any(p.search("Don't forget to commit your changes.") for p in INSTRUCTIONAL_PATTERNS))

    def test_the_key_is_to(self):
        self.assertTrue(any(p.search("The key is to keep the changes small.") for p in INSTRUCTIONAL_PATTERNS))

    def test_the_trick_is_to(self):
        self.assertTrue(any(p.search("The trick is to use a different approach.") for p in INSTRUCTIONAL_PATTERNS))

    def test_the_important_thing_is_to(self):
        self.assertTrue(any(p.search("The important thing is to stay consistent.") for p in INSTRUCTIONAL_PATTERNS))

    def test_you_need_to(self):
        self.assertTrue(any(p.search("You need to install the dependencies.") for p in INSTRUCTIONAL_PATTERNS))

    def test_you_have_to(self):
        self.assertTrue(any(p.search("You have to configure the environment.") for p in INSTRUCTIONAL_PATTERNS))

    def test_you_must(self):
        self.assertTrue(any(p.search("You must verify the output.") for p in INSTRUCTIONAL_PATTERNS))

    def test_you_should(self):
        self.assertTrue(any(p.search("You should review the documentation.") for p in INSTRUCTIONAL_PATTERNS))

    def test_what_you_need_to_do_is(self):
        self.assertTrue(any(p.search("What you need to do is restart the service.") for p in INSTRUCTIONAL_PATTERNS))

    def test_in_order_to(self):
        self.assertTrue(any(p.search("In order to fix this, run the diagnostic.") for p in INSTRUCTIONAL_PATTERNS))

    def test_not_declarative(self):
        self.assertFalse(any(p.search("The process completed successfully.") for p in INSTRUCTIONAL_PATTERNS))


# ── Negative Imperative Patterns ─────────────────────────────────────


class TestNegativeImperativePatterns(unittest.TestCase):
    def test_dont_worry(self):
        self.assertTrue(any(p.search("Don't worry about it.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_dont_forget(self):
        self.assertTrue(any(p.search("Don't forget to save.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_dont_run(self):
        self.assertTrue(any(p.search("Don't run this command.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_dont_skip(self):
        self.assertTrue(any(p.search("Don't skip the tests.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_do_not_attempt(self):
        self.assertTrue(any(p.search("Do not attempt to modify this file.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_do_not_exceed(self):
        self.assertTrue(any(p.search("Do not exceed the maximum limit.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_do_not_ignore(self):
        self.assertTrue(any(p.search("Do not ignore the warnings.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_never_ignore(self):
        self.assertTrue(any(p.search("Never ignore error messages.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_never_skip(self):
        self.assertTrue(any(p.search("Never skip the validation step.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_avoid_using(self):
        self.assertTrue(any(p.search("Avoid using global variables.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_avoid_this(self):
        self.assertTrue(any(p.search("Avoid this pattern.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_refrain_from(self):
        self.assertTrue(any(p.search("Refrain from editing this file.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_steer_clear_of(self):
        self.assertTrue(any(p.search("Steer clear of deprecated APIs.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_stay_away_from(self):
        self.assertTrue(any(p.search("Stay away from mutable state.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_be_careful_not_to(self):
        self.assertTrue(any(p.search("Be careful not to overwrite the backup.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_take_care_not_to(self):
        self.assertTrue(any(p.search("Take care not to expose the key.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_no_smoking(self):
        self.assertTrue(any(p.search("No smoking.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_no_parking(self):
        self.assertTrue(any(p.search("No parking.") for p in NEGATIVE_IMPERATIVE_PATTERNS))

    def test_not_declarative(self):
        self.assertFalse(any(p.search("She did not attend the meeting.") for p in NEGATIVE_IMPERATIVE_PATTERNS))


# ── Main class: WriterImperativeDensity ──────────────────────────────


class TestWriterImperativeDensity(unittest.TestCase):
    def setUp(self):
        self.wid = WriterImperativeDensity()

    def test_empty_text(self):
        result = self.wid.measure("")
        self.assertEqual(result["imperative_density_index"], 0.0)
        self.assertEqual(result["classification"], "declarative")

    def test_pure_narrative(self):
        text = (
            "The rain fell steadily through the afternoon. "
            "She watched the water collect in the gutters. "
            "The coffee had gone cold hours ago. "
            "A cat sat in the window across the street. "
            "The light changed from grey to a deeper grey. "
            "Somewhere a door closed."
        )
        result = self.wid.measure(text)
        self.assertLess(result["imperative_density_index"], 0.05)
        self.assertEqual(result["classification"], "declarative")

    def test_pure_instructional(self):
        text = (
            "First, open the terminal. "
            "Next, run the install command. "
            "Make sure to check the output. "
            "Don't skip the tests. "
            "Then, configure the settings. "
            "Remember to set the API key. "
            "Finally, restart the server."
        )
        result = self.wid.measure(text)
        self.assertGreater(result["imperative_density_index"], 0.0)
        self.assertIn(result["classification"], [
            "moderately_imperative",
            "heavily_instructional",
            "command_saturated",
        ])

    def test_mixed_text(self):
        text = (
            "The project grew steadily over the months. "
            "Consider the impact of each change. "
            "The team worked through the weekend. "
            "Please review the pull request. "
            "Tests passed without errors."
        )
        result = self.wid.measure(text)
        self.assertGreater(result["imperative_density_index"], 0.0)
        self.assertLessEqual(result["imperative_density_index"], 1.0)

    def test_softened_imperatives(self):
        text = (
            "Please consider the alternatives. "
            "Kindly review the attached document. "
            "You might want to check the logs. "
            "Feel free to ask questions. "
            "Perhaps consider a different approach."
        )
        result = self.wid.measure(text)
        self.assertGreater(result["softened_imperative_rate"], 0.0)

    def test_hortative_text(self):
        text = (
            "Let's examine the evidence. "
            "Let us consider the implications. "
            "Let me show you the results. "
            "Shall we begin?"
        )
        result = self.wid.measure(text)
        self.assertGreater(result["hortative_rate"], 0.0)

    def test_negative_imperatives(self):
        text = (
            "Don't worry about the warnings. "
            "Never skip the validation step. "
            "Avoid using global variables. "
            "Do not attempt to modify this file. "
            "Refrain from editing the config."
        )
        result = self.wid.measure(text)
        self.assertGreater(result["negative_imperative_rate"], 0.0)

    def test_recipe_text_classification(self):
        text = (
            "First, chop the onions finely. "
            "Next, heat the oil in a pan. "
            "Add the garlic and stir. "
            "Then, add the tomatoes. "
            "Don't forget to season with salt. "
            "Let it simmer for twenty minutes. "
            "Serve hot with fresh basil."
        )
        result = self.wid.measure(text)
        self.assertIn(result["classification"], [
            "moderately_imperative",
            "heavily_instructional",
            "command_saturated",
        ])

    def test_academic_text_classification(self):
        text = (
            "The committee reviewed the quarterly financial statements. "
            "Revenue increased by twelve percent compared to the previous period. "
            "Operating expenses remained within the approved allocation. "
            "The board confirmed the capital expenditure plan. "
            "All members voted in favor of the resolution."
        )
        result = self.wid.measure(text)
        self.assertIn(result["classification"], [
            "declarative",
            "occasionally_directive",
        ])

    def test_index_bounded(self):
        text = "Stop. Wait. Listen. First, open the file. Don't skip tests. Let's go. Please review. The cat sat."
        result = self.wid.measure(text)
        self.assertGreaterEqual(result["imperative_density_index"], 0.0)
        self.assertLessEqual(result["imperative_density_index"], 1.0)

    def test_single_sentence(self):
        result = self.wid.measure("Hello world.")
        self.assertIn("imperative_density_index", result)

    def test_only_imperatives(self):
        text = "Stop. Wait. Go. Listen. Look. Run. Come. Stay. Read. Write."
        result = self.wid.measure(text)
        self.assertGreater(result["imperative_density_index"], 0.0)

    def test_result_keys_present(self):
        result = self.wid.measure("The cat sat on the mat.")
        expected_keys = {
            "direct_imperative_rate",
            "softened_imperative_rate",
            "hortative_rate",
            "instructional_rate",
            "negative_imperative_rate",
            "imperative_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_classify_declarative(self):
        self.assertEqual(self.wid.classify(0.0), "declarative")
        self.assertEqual(self.wid.classify(0.04), "declarative")

    def test_classify_occasionally_directive(self):
        self.assertEqual(self.wid.classify(0.05), "occasionally_directive")
        self.assertEqual(self.wid.classify(0.14), "occasionally_directive")

    def test_classify_moderately_imperative(self):
        self.assertEqual(self.wid.classify(0.15), "moderately_imperative")
        self.assertEqual(self.wid.classify(0.29), "moderately_imperative")

    def test_classify_heavily_instructional(self):
        self.assertEqual(self.wid.classify(0.30), "heavily_instructional")
        self.assertEqual(self.wid.classify(0.49), "heavily_instructional")

    def test_classify_command_saturated(self):
        self.assertEqual(self.wid.classify(0.50), "command_saturated")
        self.assertEqual(self.wid.classify(0.80), "command_saturated")

    def test_compute_index_weights(self):
        # Verify weights are applied correctly
        index = self.wid.compute_imperative_density_index(
            direct=1.0,
            softened=0.0,
            hortative=0.0,
            instructional=0.0,
            negative=0.0,
        )
        self.assertAlmostEqual(index, 0.30, places=2)

    def test_compute_index_all_max(self):
        index = self.wid.compute_imperative_density_index(
            direct=1.0,
            softened=1.0,
            hortative=1.0,
            instructional=1.0,
            negative=1.0,
        )
        self.assertEqual(index, 1.0)

    def test_compute_index_all_zero(self):
        index = self.wid.compute_imperative_density_index(
            direct=0.0,
            softened=0.0,
            hortative=0.0,
            instructional=0.0,
            negative=0.0,
        )
        self.assertEqual(index, 0.0)

    def test_compute_index_capped_at_one(self):
        index = self.wid.compute_imperative_density_index(
            direct=2.0,
            softened=2.0,
            hortative=2.0,
            instructional=2.0,
            negative=2.0,
        )
        self.assertLessEqual(index, 1.0)


# ── Integration: realistic texts ─────────────────────────────────────


class TestIntegrationRealisticTexts(unittest.TestCase):
    def setUp(self):
        self.wid = WriterImperativeDensity()

    def test_tutorial_text(self):
        text = (
            "First, clone the repository from GitHub. "
            "Next, install the dependencies using pip. "
            "Make sure to create a virtual environment. "
            "Then, run the test suite to verify everything works. "
            "Don't forget to set the environment variables. "
            "After that, start the development server. "
            "Finally, open your browser and navigate to localhost."
        )
        result = self.wid.measure(text)
        self.assertGreater(result["imperative_density_index"], 0.1)
        self.assertIn(result["classification"], [
            "moderately_imperative",
            "heavily_instructional",
            "command_saturated",
        ])

    def test_military_orders(self):
        text = (
            "Move to the north ridge. "
            "Hold position until dawn. "
            "Don't engage without confirmation. "
            "Watch the eastern approach. "
            "Report any movement. "
            "Stay off the radio unless necessary. "
            "Wait for the signal."
        )
        result = self.wid.measure(text)
        self.assertGreater(result["direct_imperative_rate"], 0.0)

    def test_polite_email(self):
        text = (
            "Please find the report attached. "
            "Kindly review it before the meeting. "
            "Feel free to add your comments. "
            "Don't hesitate to reach out with questions. "
            "The meeting is scheduled for Thursday."
        )
        result = self.wid.measure(text)
        self.assertGreater(result["softened_imperative_rate"], 0.0)

    def test_philosophical_essay(self):
        text = (
            "The question of consciousness remains one of philosophy's deepest puzzles. "
            "We experience the world subjectively, yet struggle to explain how matter "
            "gives rise to experience. "
            "The gap between neural activity and felt sensation persists. "
            "Some argue that consciousness is an illusion. "
            "Others maintain that it is a fundamental feature of reality. "
            "The debate continues without resolution."
        )
        result = self.wid.measure(text)
        self.assertLess(result["imperative_density_index"], 0.05)


if __name__ == "__main__":
    unittest.main()
