#!/usr/bin/env python3
"""Tests for writer_caveat_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_caveat_density import (
    CaveatDensityResult,
    measure_caveat_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_caveat_density("")
        assert r.caveat_density_index == 0.0
        assert r.classification == "uncaveated"

    def test_whitespace_only(self):
        r = measure_caveat_density("   \n\n   ")
        assert r.caveat_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_caveat_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1

    def test_single_word(self):
        r = measure_caveat_density("Hello.")
        assert r.caveat_density_index == 0.0
        assert r.classification == "uncaveated"

    def test_no_caveat_plain_sentence(self):
        r = measure_caveat_density("The cat sat on the mat.")
        assert r.adversative_count == 0
        assert r.scope_limiter_count == 0
        assert r.exception_marker_count == 0


# ── uncaveated prose ────────────────────────────────────────────


class TestUncaveatedProse:
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

    def test_uncaveated_classification(self):
        r = measure_caveat_density(self.PLAIN)
        assert r.classification in ("uncaveated", "lightly_caveated")
        assert r.caveat_density_index < 0.15

    def test_no_adversative(self):
        r = measure_caveat_density(self.PLAIN)
        assert r.adversative_count == 0

    def test_no_scope_limiter(self):
        r = measure_caveat_density(self.PLAIN)
        assert r.scope_limiter_count == 0

    def test_no_preemptive(self):
        r = measure_caveat_density(self.PLAIN)
        assert r.preemptive_concession_count == 0

    def test_no_exception(self):
        r = measure_caveat_density(self.PLAIN)
        assert r.exception_marker_count == 0

    def test_no_provisional(self):
        r = measure_caveat_density(self.PLAIN)
        assert r.provisional_count == 0

    def test_no_qualification(self):
        r = measure_caveat_density(self.PLAIN)
        assert r.qualification_adverb_count == 0


# ── heavily caveated prose ──────────────────────────────────────


class TestHeavilyCaveatedProse:
    ACADEMIC = (
        "The results suggest a correlation, although causation cannot be established. "
        "Generally speaking, participants showed improvement in most cases. "
        "However, this finding is limited to the study population. "
        "Admittedly, the sample size was small, and results may not generalize. "
        "In principle, the approach should work, provided that the input data is clean. "
        "To be fair, prior studies reached similar conclusions, albeit with different methods. "
        "Typically, such interventions produce moderate effects, barring unforeseen variables. "
        "Nevertheless, the evidence is compelling, at least to a certain extent. "
        "Of course, one could argue that the methodology has limitations. "
        "Subject to replication, these findings offer preliminary support for the hypothesis. "
        "While it is true that confounds exist, the overall pattern is consistent. "
        "In practice, the implementation depends on available resources. "
        "Theoretically, the model predicts improvement, all else being equal. "
        "That said, alternative explanations cannot be ruled out entirely. "
        "Except for the outlier group, participants benefited from the treatment."
    )

    def test_heavily_caveated_classification(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.classification in (
            "heavily_caveated",
            "caveat_saturated",
            "moderately_caveated",
        )
        assert r.caveat_density_index >= 0.15

    def test_high_adversative_count(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.adversative_count >= 3

    def test_high_scope_count(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.scope_limiter_count >= 2

    def test_high_preemptive_count(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.preemptive_concession_count >= 2

    def test_high_exception_count(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.exception_marker_count >= 1

    def test_high_provisional_count(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.provisional_count >= 2

    def test_high_qualification_count(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.qualification_adverb_count >= 2

    def test_diversity_nonzero(self):
        r = measure_caveat_density(self.ACADEMIC)
        assert r.caveat_diversity_index > 0.0


# ── adversative conjunctions ────────────────────────────────────


class TestAdversative:
    def test_however(self):
        r = measure_caveat_density("The plan is sound. However, risks remain.")
        assert r.adversative_count >= 1

    def test_although(self):
        r = measure_caveat_density("Although the code compiles, tests are failing.")
        assert r.adversative_count >= 1

    def test_nevertheless(self):
        r = measure_caveat_density("The API is slow. Nevertheless, it meets requirements.")
        assert r.adversative_count >= 1

    def test_nonetheless(self):
        r = measure_caveat_density("Budget is tight. Nonetheless, the project proceeds.")
        assert r.adversative_count >= 1

    def test_on_the_other_hand(self):
        r = measure_caveat_density("The design is clean. On the other hand, it lacks flexibility.")
        assert r.adversative_count >= 1

    def test_conversely(self):
        r = measure_caveat_density("High latency helps diagnosis. Conversely, it hurts throughput.")
        assert r.adversative_count >= 1

    def test_that_said(self):
        r = measure_caveat_density("The algorithm is fast. That said, memory usage is high.")
        assert r.adversative_count >= 1

    def test_having_said_that(self):
        r = measure_caveat_density("The approach works. Having said that, edge cases exist.")
        assert r.adversative_count >= 1

    def test_multiple_adversative(self):
        text = (
            "However, the initial results were promising. "
            "Although the dataset was limited, patterns emerged. "
            "Nevertheless, the team continued. "
            "The design, albeit imperfect, served its purpose."
        )
        r = measure_caveat_density(text)
        assert r.adversative_count >= 4


# ── scope limiters ──────────────────────────────────────────────


class TestScopeLimiters:
    def test_in_some_cases(self):
        r = measure_caveat_density("In some cases, the cache invalidates early.")
        assert r.scope_limiter_count >= 1

    def test_under_certain_conditions(self):
        r = measure_caveat_density("Under certain conditions, the lock is released.")
        assert r.scope_limiter_count >= 1

    def test_to_a_certain_extent(self):
        r = measure_caveat_density("The fix works, to a certain extent.")
        assert r.scope_limiter_count >= 1

    def test_for_the_most_part(self):
        r = measure_caveat_density("For the most part, users reported satisfaction.")
        assert r.scope_limiter_count >= 1

    def test_in_practice(self):
        r = measure_caveat_density("In practice, the overhead is negligible.")
        assert r.scope_limiter_count >= 1

    def test_in_most_cases(self):
        r = measure_caveat_density("In most cases, the default configuration suffices.")
        assert r.scope_limiter_count >= 1

    def test_generally_speaking(self):
        r = measure_caveat_density("Generally speaking, the migration is non-destructive.")
        assert r.scope_limiter_count >= 1

    def test_on_the_whole(self):
        r = measure_caveat_density("On the whole, the refactor improved readability.")
        assert r.scope_limiter_count >= 1

    def test_as_far_as(self):
        r = measure_caveat_density("As far as performance goes, the change is neutral.")
        assert r.scope_limiter_count >= 1

    def test_insofar_as(self):
        r = measure_caveat_density("The fix helps insofar as it prevents data loss.")
        assert r.scope_limiter_count >= 1


# ── preemptive concessions ──────────────────────────────────────


class TestPreemptiveConcessions:
    def test_admittedly(self):
        r = measure_caveat_density("Admittedly, the test coverage is incomplete.")
        assert r.preemptive_concession_count >= 1

    def test_to_be_fair(self):
        r = measure_caveat_density("To be fair, the deadline was unrealistic.")
        assert r.preemptive_concession_count >= 1

    def test_of_course(self):
        r = measure_caveat_density("Of course, this assumes a stable network.")
        assert r.preemptive_concession_count >= 1

    def test_granted(self):
        r = measure_caveat_density("Granted, the initial version had bugs.")
        assert r.preemptive_concession_count >= 1

    def test_to_be_sure(self):
        r = measure_caveat_density("To be sure, the metrics are only approximate.")
        assert r.preemptive_concession_count >= 1

    def test_one_could_argue(self):
        r = measure_caveat_density("One could argue that simpler designs exist.")
        assert r.preemptive_concession_count >= 1

    def test_one_might_say(self):
        r = measure_caveat_density("One might say the API is over-engineered.")
        assert r.preemptive_concession_count >= 1

    def test_it_is_true_that(self):
        r = measure_caveat_density("It is true that the migration takes time.")
        assert r.preemptive_concession_count >= 1

    def test_while_it_is_true_that(self):
        r = measure_caveat_density(
            "While it is true that costs are high, the benefits outweigh them."
        )
        assert r.preemptive_concession_count >= 1

    def test_could_object(self):
        r = measure_caveat_density("Critics might object that the study lacks controls.")
        assert r.preemptive_concession_count >= 1

    def test_to_be_clear(self):
        r = measure_caveat_density("To be clear, this is not a regression.")
        assert r.preemptive_concession_count >= 1


# ── exception markers ───────────────────────────────────────────


class TestExceptionMarkers:
    def test_except_for(self):
        r = measure_caveat_density("All tests pass except for the integration suite.")
        assert r.exception_marker_count >= 1

    def test_with_the_exception_of(self):
        r = measure_caveat_density(
            "All modules are stable, with the exception of the auth layer."
        )
        assert r.exception_marker_count >= 1

    def test_apart_from(self):
        r = measure_caveat_density("Apart from the latency issue, performance is good.")
        assert r.exception_marker_count >= 1

    def test_aside_from(self):
        r = measure_caveat_density("Aside from the cost, the solution is ideal.")
        assert r.exception_marker_count >= 1

    def test_barring(self):
        r = measure_caveat_density("Barring unexpected outages, the deploy finishes at midnight.")
        assert r.exception_marker_count >= 1

    def test_unless(self):
        r = measure_caveat_density("The process completes automatically unless the queue is full.")
        assert r.exception_marker_count >= 1

    def test_save_for(self):
        r = measure_caveat_density("Save for one edge case, the refactor is complete.")
        assert r.exception_marker_count >= 1

    def test_excluding(self):
        r = measure_caveat_density("Excluding test files, the codebase has 5000 lines.")
        assert r.exception_marker_count >= 1

    def test_in_the_event_that(self):
        r = measure_caveat_density("In the event that the server restarts, data is preserved.")
        assert r.exception_marker_count >= 1

    def test_in_the_absence_of(self):
        r = measure_caveat_density("In the absence of network errors, the sync completes.")
        assert r.exception_marker_count >= 1

    def test_multiple_exceptions(self):
        text = (
            "Except for the auth module, everything works. "
            "Unless the cache is stale, results are accurate. "
            "Barring power failure, the backup finishes nightly. "
            "Apart from one regression, the release is clean."
        )
        r = measure_caveat_density(text)
        assert r.exception_marker_count >= 4


# ── provisional language ────────────────────────────────────────


class TestProvisional:
    def test_in_principle(self):
        r = measure_caveat_density("In principle, the algorithm is correct.")
        assert r.provisional_count >= 1

    def test_theoretically(self):
        r = measure_caveat_density("Theoretically, throughput scales linearly.")
        assert r.provisional_count >= 1

    def test_on_paper(self):
        r = measure_caveat_density("On paper, the architecture handles 10k requests.")
        assert r.provisional_count >= 1

    def test_ideally(self):
        r = measure_caveat_density("Ideally, we would have more test coverage.")
        assert r.provisional_count >= 1

    def test_all_else_being_equal(self):
        r = measure_caveat_density("All else being equal, the simpler design wins.")
        assert r.provisional_count >= 1

    def test_assuming_that(self):
        r = measure_caveat_density("Assuming that the input is well-formed, parsing succeeds.")
        assert r.provisional_count >= 1

    def test_contingent_on(self):
        r = measure_caveat_density("Success is contingent on timely data delivery.")
        assert r.provisional_count >= 1

    def test_subject_to(self):
        r = measure_caveat_density("The schedule is subject to change without notice.")
        assert r.provisional_count >= 1

    def test_provided_that(self):
        r = measure_caveat_density("The system recovers, provided that the disk is not full.")
        assert r.provisional_count >= 1

    def test_as_long_as(self):
        r = measure_caveat_density("The cache stays warm as long as traffic is steady.")
        assert r.provisional_count >= 1

    def test_in_an_ideal_world(self):
        r = measure_caveat_density("In an ideal world, every function would have a test.")
        assert r.provisional_count >= 1

    def test_in_theory(self):
        r = measure_caveat_density("In theory, the model generalizes to unseen data.")
        assert r.provisional_count >= 1


# ── qualification adverbs ───────────────────────────────────────


class TestQualificationAdverbs:
    def test_generally(self):
        r = measure_caveat_density("Generally, the response time is under 200ms.")
        assert r.qualification_adverb_count >= 1

    def test_typically(self):
        r = measure_caveat_density("Typically, the queue drains within minutes.")
        assert r.qualification_adverb_count >= 1

    def test_usually(self):
        r = measure_caveat_density("Usually, the deploy takes five minutes.")
        assert r.qualification_adverb_count >= 1

    def test_predominantly(self):
        r = measure_caveat_density("The errors are predominantly network-related.")
        assert r.qualification_adverb_count >= 1

    def test_largely(self):
        r = measure_caveat_density("The migration was largely successful.")
        assert r.qualification_adverb_count >= 1

    def test_mostly(self):
        r = measure_caveat_density("The output is mostly correct.")
        assert r.qualification_adverb_count >= 1

    def test_primarily(self):
        r = measure_caveat_density("The bottleneck is primarily disk I/O.")
        assert r.qualification_adverb_count >= 1

    def test_arguably(self):
        r = measure_caveat_density("This is arguably the best approach.")
        assert r.qualification_adverb_count >= 1

    def test_presumably(self):
        r = measure_caveat_density("Presumably, the backup completed overnight.")
        assert r.qualification_adverb_count >= 1

    def test_ostensibly(self):
        r = measure_caveat_density("The ostensibly simple fix introduced a regression.")
        assert r.qualification_adverb_count >= 1

    def test_conceivably(self):
        r = measure_caveat_density("Conceivably, the issue could recur under load.")
        assert r.qualification_adverb_count >= 1

    def test_tends_to(self):
        r = measure_caveat_density("The system tends to slow down during peak hours.")
        assert r.qualification_adverb_count >= 1

    def test_multiple_qualifiers(self):
        text = (
            "Generally, the process is reliable. "
            "Typically, it completes within minutes. "
            "Usually, errors are transient. "
            "Largely, the system self-heals. "
            "Primarily, failures stem from network issues."
        )
        r = measure_caveat_density(text)
        assert r.qualification_adverb_count >= 5


# ── classification thresholds ────────────────────────────────────


class TestClassificationThresholds:
    def test_uncaveated(self):
        text = "The server runs the process. The output goes to a file. Done."
        r = measure_caveat_density(text)
        assert r.classification == "uncaveated"

    def test_lightly_caveated(self):
        text = (
            "The process runs on the server every morning. "
            "Output is logged to a file in the data directory. "
            "Results are formatted as JSON for downstream consumption. "
            "Configuration is handled automatically via environment variables. "
            "No manual intervention is needed under normal operation. "
            "The scheduler checks health endpoints before dispatching. "
            "Errors are written to stderr and captured by the logger. "
            "Restart behavior is idempotent by design. "
            "The backoff strategy on failure uses exponential delay. "
            "Logs rotate weekly and compress to gzip."
        )
        r = measure_caveat_density(text)
        assert r.classification in ("uncaveated", "lightly_caveated")

    def test_moderately_caveated(self):
        text = (
            "Generally, the approach works well in practice. "
            "However, edge cases require special handling. "
            "Although the algorithm is theoretically optimal, constant factors matter. "
            "In most cases, the default settings suffice. "
            "Admittedly, the documentation could be more thorough. "
            "Provided that inputs are valid, the parser handles all formats. "
            "Typically, the cache hit rate exceeds ninety percent."
        )
        r = measure_caveat_density(text)
        assert r.caveat_density_index >= 0.15

    def test_caveat_saturated(self):
        text = (
            "However, this is generally true only in some cases. "
            "Although the results are typically reliable, admittedly there are limitations. "
            "Nevertheless, in principle the approach works, barring edge cases. "
            "Of course, one could argue that, theoretically, the model is provisional. "
            "That said, ideally the system recovers, except for catastrophic failures. "
            "Conversely, largely the output is mostly correct, subject to noise. "
            "Granted, while it is true that the fix helps, to a certain extent problems remain. "
            "Nonetheless, generally speaking, the design is arguably sound. "
            "On the other hand, presumably the tests pass, unless the environment differs. "
            "To be fair, under certain conditions, the results are arguably acceptable."
        )
        r = measure_caveat_density(text)
        assert r.caveat_density_index >= 0.35


# ── rates ────────────────────────────────────────────────────────


class TestRates:
    def test_rates_scale_with_sentences(self):
        short = "However, the fix works. Generally, it is reliable."
        r = measure_caveat_density(short)
        assert r.adversative_rate > 0 or r.qualification_adverb_rate > 0
        assert r.total_sentences == 2

    def test_rate_zero_for_plain_text(self):
        text = "The file exists. The process completed. The output was saved."
        r = measure_caveat_density(text)
        assert r.adversative_rate == 0.0
        assert r.scope_limiter_rate == 0.0
        assert r.provisional_rate == 0.0


# ── composite and diversity ──────────────────────────────────────


class TestComposite:
    def test_composite_range(self):
        texts = [
            "Plain text with no caveats at all.",
            "However, the fix is generally reliable in most cases.",
            "Although theoretically sound, ideally it works barring failures.",
        ]
        for text in texts:
            r = measure_caveat_density(text)
            assert 0.0 <= r.caveat_density_index <= 1.0

    def test_diversity_range(self):
        texts = [
            "Plain text.",
            "However, although, nevertheless, admittedly, generally, typically.",
        ]
        for text in texts:
            r = measure_caveat_density(text)
            assert 0.0 <= r.caveat_diversity_index <= 1.0

    def test_more_caveats_higher_index(self):
        plain = (
            "The committee met on Tuesday. "
            "Three proposals were reviewed. "
            "The budget was approved for next quarter. "
            "Staff will receive updated guidelines. "
            "The next meeting is in December."
        )
        caveated = (
            "However, the committee met on Tuesday, generally as scheduled. "
            "Although three proposals were reviewed, in most cases they passed. "
            "Admittedly, the budget was approved, subject to revision. "
            "Typically, staff will receive guidelines, barring delays. "
            "In principle, the next meeting is in December, provided rooms are available."
        )
        r_plain = measure_caveat_density(plain)
        r_caveat = measure_caveat_density(caveated)
        assert r_caveat.caveat_density_index > r_plain.caveat_density_index

    def test_diversity_increases_with_variety(self):
        low_div = "However, the fix works. However, it is slow. However, tests pass."
        high_div = (
            "However, the fix works. Although it is slow, generally tests pass. "
            "Admittedly, typically the design is sound, barring edge cases. "
            "Nevertheless, ideally the approach is theoretically valid."
        )
        r_low = measure_caveat_density(low_div)
        r_high = measure_caveat_density(high_div)
        assert r_high.caveat_diversity_index >= r_low.caveat_diversity_index


# ── orthogonality ────────────────────────────────────────────────


class TestOrthogonality:
    def test_caveat_without_hedging(self):
        """Caveated text can be certain (no hedging)."""
        text = (
            "The algorithm is correct, however, only for sorted inputs. "
            "The fix works, except for the auth module. "
            "Generally, the process completes in five minutes."
        )
        r = measure_caveat_density(text)
        assert r.adversative_count >= 1
        assert r.exception_marker_count >= 1
        assert r.qualification_adverb_count >= 1

    def test_caveat_without_conviction_change(self):
        """Caveated text can be fully convicted."""
        text = (
            "This is the correct approach, provided that the input is valid. "
            "The system recovers automatically, barring power failure. "
            "All tests pass, except for the known flaky integration test."
        )
        r = measure_caveat_density(text)
        assert r.provisional_count >= 1
        assert r.exception_marker_count >= 2

    def test_caveat_without_emphasis(self):
        """Caveated text need not use emphasis techniques."""
        text = (
            "The process runs nightly, generally without issue. "
            "However, on weekends the schedule differs. "
            "In most cases, results are available by morning."
        )
        r = measure_caveat_density(text)
        assert r.qualification_adverb_count >= 1
        assert r.adversative_count >= 1
        assert r.scope_limiter_count >= 1


# ── metadata ─────────────────────────────────────────────────────


class TestMetadata:
    def test_total_sentences_nonzero(self):
        r = measure_caveat_density("One sentence. Two sentences.")
        assert r.total_sentences == 2

    def test_details_dict_populated(self):
        r = measure_caveat_density(
            "However, the fix is generally reliable. Admittedly, tests pass."
        )
        assert "caveat_density_index" in r.details
        assert "classification" in r.details
        assert "adversative_rate" in r.details

    def test_result_dataclass_defaults(self):
        r = CaveatDensityResult()
        assert r.adversative_count == 0
        assert r.caveat_density_index == 0.0
        assert r.classification == "uncaveated"
        assert r.details == {}

    def test_counts_match_rates_direction(self):
        text = (
            "However, the fix works. Although slow, it is reliable. "
            "Generally, the system recovers. Nevertheless, monitoring helps."
        )
        r = measure_caveat_density(text)
        assert r.adversative_count > 0
        assert r.adversative_rate > 0
        assert r.qualification_adverb_count > 0
        assert r.qualification_adverb_rate > 0


# ── edge cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence_with_caveat(self):
        r = measure_caveat_density("However, the fix generally works.")
        assert r.adversative_count >= 1
        assert r.qualification_adverb_count >= 1
        assert r.total_sentences == 1

    def test_long_text_no_caveats(self):
        sentences = [
            f"The process step {i} completed successfully." for i in range(20)
        ]
        text = " ".join(sentences)
        r = measure_caveat_density(text)
        assert r.classification == "uncaveated"
        assert r.caveat_density_index < 0.05

    def test_all_categories_present(self):
        text = (
            "However, the approach generally works. "
            "In some cases, exceptions arise. "
            "Admittedly, the fix is provisional. "
            "Except for edge cases, the system is stable. "
            "In principle, the design is sound. "
            "Typically, results are consistent."
        )
        r = measure_caveat_density(text)
        assert r.adversative_count >= 1
        assert r.scope_limiter_count >= 1
        assert r.preemptive_concession_count >= 1
        assert r.exception_marker_count >= 1
        assert r.provisional_count >= 1
        assert r.qualification_adverb_count >= 1
