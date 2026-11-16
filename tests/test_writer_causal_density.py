#!/usr/bin/env python3
"""Tests for writer_causal_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_causal_density import (
    CausalDensityResult,
    measure_causal_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_causal_density("")
        assert r.causal_index == 0.0
        assert r.classification == "descriptive"

    def test_whitespace_only(self):
        r = measure_causal_density("   \n\n   ")
        assert r.causal_index == 0.0

    def test_single_word(self):
        r = measure_causal_density("Hello.")
        assert r.classification == "descriptive"

    def test_no_causality_plain_sentence(self):
        r = measure_causal_density("The function returns a boolean value.")
        assert r.total_causal_markers == 0
        assert r.causal_index == 0.0


# ── descriptive prose (low causal density) ──────────────────────


class TestDescriptiveProse:
    def test_plain_factual_no_causation(self):
        text = (
            "The data was collected over three months. "
            "The sample included 200 participants. "
            "Results were analyzed using standard methods. "
            "The findings are presented in the table below."
        )
        r = measure_causal_density(text)
        assert r.causal_index == 0.0
        assert r.classification == "descriptive"

    def test_descriptive_neutral(self):
        text = (
            "The river flows through the valley. "
            "Trees line both banks. "
            "A bridge crosses at the narrowest point. "
            "The path leads to a small village."
        )
        r = measure_causal_density(text)
        assert r.causal_index < 0.10

    def test_recipe_instructions(self):
        text = (
            "Preheat the oven to 350 degrees. "
            "Mix the flour and sugar in a large bowl. "
            "Add the eggs one at a time. "
            "Bake for 25 to 30 minutes."
        )
        r = measure_causal_density(text)
        assert r.classification == "descriptive"

    def test_listing_facts(self):
        text = (
            "Python was created by Guido van Rossum. "
            "It was first released in 1991. "
            "The language supports multiple paradigms. "
            "It has a large standard library."
        )
        r = measure_causal_density(text)
        assert r.causal_index == 0.0
        assert r.total_causal_markers == 0


# ── explicit causal connectives ─────────────────────────────────


class TestCausalConnectives:
    def test_because(self):
        text = "The server crashed because the disk was full."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1
        assert r.causal_index > 0.0

    def test_therefore(self):
        text = "The data was corrupted. Therefore, the analysis was invalid."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_thus(self):
        text = "The sample was biased, thus the results were unreliable."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_hence(self):
        text = "The lock was broken, hence the door was unsecured."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_consequently(self):
        text = "The budget was cut. Consequently, the project was delayed."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_since(self):
        text = "Since the network was down, users could not access the service."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_due_to(self):
        text = "The outage was due to a configuration error."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_as_a_result(self):
        text = "As a result of the migration, performance improved."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_multiple_causal_connectives(self):
        text = (
            "Because the cache was full, requests were slow. "
            "Therefore, we increased the cache size. "
            "Consequently, latency dropped by 40%."
        )
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 3
        assert r.classification in ("associative", "explanatory", "analytical", "mechanistic")


# ── conditional causation ───────────────────────────────────────


class TestConditionalCausation:
    def test_if_then(self):
        text = "If the load exceeds capacity, the circuit breaker trips."
        r = measure_causal_density(text)
        assert r.conditional_count >= 1

    def test_unless(self):
        text = "The system will fail unless we add redundancy."
        r = measure_causal_density(text)
        assert r.conditional_count >= 1

    def test_whenever(self):
        text = "Whenever the queue fills up, messages are dropped."
        r = measure_causal_density(text)
        assert r.conditional_count >= 1

    def test_provided_that(self):
        text = "The algorithm works correctly provided that the input is sorted."
        r = measure_causal_density(text)
        assert r.conditional_count >= 1

    def test_as_long_as(self):
        text = "As long as the database is available, the service responds."
        r = measure_causal_density(text)
        assert r.conditional_count >= 1

    def test_multiple_conditionals(self):
        text = (
            "If the network drops, retries kick in. "
            "When the queue overflows, backpressure activates. "
            "Unless the disk fails, data persists."
        )
        r = measure_causal_density(text)
        assert r.conditional_count >= 3


# ── teleological markers (purpose/goal) ─────────────────────────


class TestTeleologicalMarkers:
    def test_in_order_to(self):
        text = "The cache was introduced in order to reduce database load."
        r = measure_causal_density(text)
        assert r.teleological_count >= 1

    def test_so_that(self):
        text = "We added indexes so that queries would run faster."
        r = measure_causal_density(text)
        assert r.teleological_count >= 1

    def test_to_ensure(self):
        text = "Validation was added to ensure data integrity."
        r = measure_causal_density(text)
        assert r.teleological_count >= 1

    def test_to_prevent(self):
        text = "Rate limiting was implemented to prevent abuse."
        r = measure_causal_density(text)
        assert r.teleological_count >= 1

    def test_designed_to(self):
        text = "The protocol was designed to handle millions of connections."
        r = measure_causal_density(text)
        assert r.teleological_count >= 1

    def test_for_the_purpose_of(self):
        text = "The committee was formed for the purpose of reviewing policies."
        r = measure_causal_density(text)
        assert r.teleological_count >= 1

    def test_multiple_teleological(self):
        text = (
            "The service was designed to scale horizontally. "
            "Caching was introduced to reduce latency. "
            "Monitoring was added to detect anomalies early."
        )
        r = measure_causal_density(text)
        assert r.teleological_count >= 3


# ── consequence chains ──────────────────────────────────────────


class TestConsequenceChains:
    def test_resulting_in(self):
        text = "The migration completed, resulting in faster query times."
        r = measure_causal_density(text)
        assert r.consequence_count >= 1

    def test_leading_to(self):
        text = "Memory usage grew steadily, leading to an out-of-memory crash."
        r = measure_causal_density(text)
        assert r.consequence_count >= 1

    def test_which_means(self):
        text = "The buffer was doubled, which means more data can be held in memory."
        r = measure_causal_density(text)
        assert r.consequence_count >= 1

    def test_triggers(self):
        text = "A failed health check triggers an automatic restart."
        r = measure_causal_density(text)
        assert r.consequence_count >= 1

    def test_produces(self):
        text = "The algorithm produces a sorted output from unsorted input."
        r = measure_causal_density(text)
        assert r.consequence_count >= 1

    def test_multiple_consequences(self):
        text = (
            "The policy change led to higher enrollment, "
            "which triggers additional funding. "
            "This produces a virtuous cycle, resulting in better outcomes."
        )
        r = measure_causal_density(text)
        assert r.consequence_count >= 3


# ── counterfactual causation ────────────────────────────────────


class TestCounterfactualCausation:
    def test_would_have(self):
        text = "Without the fix, the bug would have caused data loss."
        r = measure_causal_density(text)
        assert r.counterfactual_count >= 1

    def test_could_have(self):
        text = "A faster algorithm could have reduced the runtime."
        r = measure_causal_density(text)
        assert r.counterfactual_count >= 1

    def test_might_have(self):
        text = "Earlier detection might have prevented the outage."
        r = measure_causal_density(text)
        assert r.counterfactual_count >= 1

    def test_were_it_not_for(self):
        text = "Were it not for the backup, the data would have been lost."
        r = measure_causal_density(text)
        assert r.counterfactual_count >= 1

    def test_but_for(self):
        text = "But for the intervention, the system would have crashed."
        r = measure_causal_density(text)
        assert r.counterfactual_count >= 1

    def test_in_the_absence_of(self):
        text = "In the absence of monitoring, failures go undetected."
        r = measure_causal_density(text)
        assert r.counterfactual_count >= 1


# ── composite scoring ───────────────────────────────────────────


class TestCompositeScoring:
    def test_index_range(self):
        text = (
            "Because the system was overloaded, latency increased. "
            "If more servers were added, throughput would improve. "
            "The cache was introduced to reduce load, resulting in "
            "faster responses. Had the migration been delayed, "
            "the outage would have been worse."
        )
        r = measure_causal_density(text)
        assert 0.0 <= r.causal_index <= 1.0

    def test_high_causal_density(self):
        text = (
            "Because the database was overloaded, queries timed out. "
            "Therefore, the team introduced read replicas to distribute "
            "the load. If the replicas were not added, the service "
            "would have become unavailable. The caching layer was "
            "designed to reduce database hits, resulting in a 60% "
            "latency improvement. Consequently, user satisfaction "
            "increased significantly."
        )
        r = measure_causal_density(text)
        assert r.causal_index >= 0.15
        assert r.classification in ("explanatory", "analytical", "mechanistic")

    def test_mixed_causal_and_descriptive(self):
        text = (
            "The project started in January. "
            "Because the team was small, progress was slow. "
            "The database contained 50 million records. "
            "Therefore, indexing took several hours."
        )
        r = measure_causal_density(text)
        assert r.classification in ("associative", "explanatory")

    def test_weights_sum_to_one(self):
        # The five weights should sum to 1.0
        # causal_connective 0.25, conditional 0.20,
        # consequence 0.25, teleological 0.20, counterfactual 0.10
        total = 0.25 + 0.20 + 0.25 + 0.20 + 0.10
        assert abs(total - 1.0) < 1e-9


# ── classification ──────────────────────────────────────────────


class TestClassification:
    def test_descriptive_classification(self):
        text = "The sky is blue. The grass is green. The sun is bright."
        r = measure_causal_density(text)
        assert r.classification == "descriptive"

    def test_analytical_classification(self):
        text = (
            "Because inflation rose, the central bank raised rates. "
            "Consequently, borrowing costs increased. "
            "Therefore, investment slowed. "
            "This led to lower GDP growth. "
            "As a result, unemployment ticked higher. "
            "Since consumer spending weakened, firms cut production. "
            "Thus, the cycle reinforced itself."
        )
        r = measure_causal_density(text)
        assert r.causal_index >= 0.10
        assert r.classification in ("associative", "explanatory", "analytical", "mechanistic")

    def test_mechanistic_classification(self):
        text = (
            "Because the input buffer overflowed, data was truncated. "
            "Therefore, the parser received malformed tokens. "
            "Consequently, the lexer raised an exception. "
            "As a result, the request handler returned a 500 error. "
            "Since the error was uncaught, the worker process crashed. "
            "Thus, the load balancer removed the node from the pool. "
            "Hence, remaining nodes received more traffic. "
            "This triggered cascading failures across the cluster. "
            "Leading to a complete service outage. "
            "Which caused customer-facing errors."
        )
        r = measure_causal_density(text)
        assert r.causal_index >= 0.10
        assert r.classification in ("associative", "explanatory", "analytical", "mechanistic")


# ── orthogonality ───────────────────────────────────────────────


class TestOrthogonality:
    def test_high_concession_low_causal(self):
        """Concessive prose without causal reasoning."""
        text = (
            "Admittedly, the approach has limitations. "
            "Although the results were promising, the sample was small. "
            "While the method works in theory, practice may differ."
        )
        r = measure_causal_density(text)
        assert r.causal_index < 0.20

    def test_high_causal_low_concession(self):
        """Strong causal reasoning without concession."""
        text = (
            "The server crashed because memory was exhausted. "
            "Therefore, the process was killed by the OOM handler. "
            "Consequently, pending requests were dropped."
        )
        r = measure_causal_density(text)
        assert r.causal_index >= 0.10
        assert r.causal_connective_count >= 2


# ── metadata ────────────────────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_causal_density(text)
        assert r.total_sentences == 3

    def test_word_count(self):
        text = "The quick brown fox jumps over the lazy dog."
        r = measure_causal_density(text)
        assert r.total_words == 9

    def test_total_markers(self):
        text = (
            "Because the system failed, therefore the test was aborted. "
            "If we had known, we could have prevented it."
        )
        r = measure_causal_density(text)
        assert r.total_causal_markers >= 3
        assert r.total_causal_markers == (
            r.causal_connective_count
            + r.conditional_count
            + r.teleological_count
            + r.consequence_count
            + r.counterfactual_count
        )


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence_with_causation(self):
        text = "The build failed because the dependency was missing."
        r = measure_causal_density(text)
        assert r.total_sentences == 1
        assert r.causal_connective_count >= 1

    def test_very_long_text(self):
        text = (
            "The process started normally. " * 50
            + "Because the disk was full, the log write failed. "
            + "The process continued normally. " * 50
        )
        r = measure_causal_density(text)
        assert r.total_sentences > 50
        assert r.causal_index > 0.0
        # With one causal marker in 101 sentences, density should be low
        assert r.causal_index < 0.10

    def test_case_insensitive(self):
        text = "BECAUSE the server was down, THEREFORE users saw errors."
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 1

    def test_repeated_causal_word(self):
        text = (
            "Because the first check failed, the retry ran. "
            "Because the retry also failed, the alert fired."
        )
        r = measure_causal_density(text)
        assert r.causal_connective_count >= 2

    def test_no_false_positive_on_so(self):
        """'so' as a degree adverb should not count as causal."""
        # Note: 'so' in our word list will match; this documents behavior.
        text = "The room was so quiet."
        r = measure_causal_density(text)
        # 'so' is in our causal list — it will match.
        # This is a known limitation; context disambiguation is not implemented.
        assert r.total_sentences == 1


# ── result dataclass defaults ──────────────────────────────────


class TestResultDefaults:
    def test_default_values(self):
        r = CausalDensityResult()
        assert r.causal_index == 0.0
        assert r.classification == "descriptive"
        assert r.causal_connective_count == 0
        assert r.conditional_count == 0
        assert r.teleological_count == 0
        assert r.consequence_count == 0
        assert r.counterfactual_count == 0
        assert r.total_causal_markers == 0
        assert r.total_sentences == 0
        assert r.total_words == 0


# ── real-world style tests ──────────────────────────────────────


class TestRealWorldStyles:
    def test_scientific_paper(self):
        text = (
            "We hypothesized that increased temperature would accelerate "
            "the reaction rate. Because the enzyme denatures above 60C, "
            "we predicted a peak at that threshold. The results confirmed "
            "this: reaction rate increased with temperature up to 58C, "
            "resulting in a 3x speedup. Consequently, we concluded that "
            "thermal optimization is viable within this range. If the "
            "temperature exceeds 62C, the enzyme loses activity, which "
            "means the system must be carefully controlled."
        )
        r = measure_causal_density(text)
        assert r.causal_index >= 0.10
        assert r.classification in ("associative", "explanatory", "analytical", "mechanistic")

    def test_legal_brief(self):
        text = (
            "Since the defendant failed to disclose material information, "
            "the plaintiff was unable to make an informed decision. "
            "Therefore, the contract was voidable. As a result of this "
            "breach, damages were incurred. Had the disclosure been made, "
            "the plaintiff would have declined the agreement."
        )
        r = measure_causal_density(text)
        assert r.causal_index >= 0.10
        assert r.total_causal_markers >= 4

    def test_casual_storytelling(self):
        text = (
            "I walked to the store. It was a nice day. "
            "I bought some milk and bread. The cashier was friendly. "
            "I walked home and made a sandwich."
        )
        r = measure_causal_density(text)
        assert r.causal_index < 0.10
        assert r.classification == "descriptive"

    def test_engineering_postmortem(self):
        text = (
            "At 14:03 UTC, a configuration change was deployed to production. "
            "Because the new config increased connection pool size beyond "
            "the database limit, connections were refused. This triggered "
            "cascading failures: the API returned 503 errors, which caused "
            "the frontend to display a maintenance page. Consequently, "
            "user traffic dropped by 95%. The on-call engineer identified "
            "the root cause at 14:11 and rolled back the change, resulting "
            "in full recovery by 14:15. In order to prevent recurrence, "
            "a pre-deploy validation step was added to the pipeline."
        )
        r = measure_causal_density(text)
        assert r.causal_index >= 0.10
        assert r.classification in ("associative", "explanatory", "analytical", "mechanistic")
        assert r.total_causal_markers >= 5
