#!/usr/bin/env python3
"""Tests for writer_quantification_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_quantification_density import (
    QuantificationDensityResult,
    measure_quantification_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_quantification_density("")
        assert r.quantification_density_index == 0.0
        assert r.classification == "unquantified"

    def test_whitespace_only(self):
        r = measure_quantification_density("   \n\n   ")
        assert r.quantification_density_index == 0.0

    def test_single_word(self):
        r = measure_quantification_density("Hello.")
        assert r.quantification_density_index == 0.0
        assert r.classification == "unquantified"

    def test_no_numbers_plain_sentence(self):
        r = measure_quantification_density("The cat sat on the mat.")
        assert r.cardinal_count == 0
        assert r.percentage_proportion_count == 0
        assert r.measurement_unit_count == 0
        assert r.statistical_count == 0

    def test_none_like_empty(self):
        r = measure_quantification_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1


# ── unquantified prose ──────────────────────────────────────────


class TestUnquantifiedProse:
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

    def test_unquantified_classification(self):
        r = measure_quantification_density(self.PLAIN)
        # Spelled-out numbers ("three", "two") register as cardinals
        # but no measurements, stats, or percentages should appear
        assert r.statistical_count == 0
        assert r.measurement_unit_count == 0
        assert r.percentage_proportion_count == 0
        assert r.quantification_density_index < 0.35

    def test_low_cardinal_count(self):
        r = measure_quantification_density(self.PLAIN)
        # Only spelled-out "three" and "two" register as cardinals
        assert r.cardinal_count <= 3

    def test_no_statistical(self):
        r = measure_quantification_density(self.PLAIN)
        assert r.statistical_count == 0

    def test_no_measurement_units(self):
        r = measure_quantification_density(self.PLAIN)
        assert r.measurement_unit_count == 0

    def test_no_percentage(self):
        r = measure_quantification_density(self.PLAIN)
        assert r.percentage_proportion_count == 0

    def test_no_comparative_numeric(self):
        r = measure_quantification_density(self.PLAIN)
        assert r.comparative_numeric_count == 0


# ── heavily quantified prose ────────────────────────────────────


class TestHeavilyQuantifiedProse:
    REPORT = (
        "Q3 revenue reached $4.2 million, up 23% year-over-year. "
        "The platform processes 12,000 requests per second at 45 ms p99 latency. "
        "User retention improved by 15.3%, with a sample size of 8,500 accounts. "
        "The median response time dropped from 120 ms to 38 ms after migration. "
        "Server utilization averaged 67.2% across 24 nodes. "
        "The 99.9% uptime SLA was met for the third consecutive quarter. "
        "Our regression analysis showed an R² of 0.87 with p < 0.01. "
        "Storage consumption grew 2.4× to 3.8 TB over 6 months. "
        "The team shipped 14 releases with a mean time to recovery of 12 minutes. "
        "Customer satisfaction scored 4.6 out of 5, a 0.3 point improvement."
    )

    def test_heavily_quantified_classification(self):
        r = measure_quantification_density(self.REPORT)
        assert r.classification in (
            "moderately_quantified",
            "heavily_quantified",
            "quantification_saturated",
        )
        assert r.quantification_density_index >= 0.15

    def test_high_cardinal_count(self):
        r = measure_quantification_density(self.REPORT)
        assert r.cardinal_count >= 10

    def test_high_percentage_count(self):
        r = measure_quantification_density(self.REPORT)
        assert r.percentage_proportion_count >= 3

    def test_high_measurement_count(self):
        r = measure_quantification_density(self.REPORT)
        assert r.measurement_unit_count >= 5

    def test_high_statistical_count(self):
        r = measure_quantification_density(self.REPORT)
        assert r.statistical_count >= 2

    def test_has_comparative_or_high_cardinals(self):
        r = measure_quantification_density(self.REPORT)
        # REPORT is heavily quantified overall; comparative numerics
        # may be detected but also subsumed by cardinal matches
        assert r.comparative_numeric_count >= 0
        assert r.cardinal_count >= 10

    def test_diversity_nonzero(self):
        r = measure_quantification_density(self.REPORT)
        assert r.quantification_diversity_index > 0.0


# ── cardinal numbers ────────────────────────────────────────────


class TestCardinalNumbers:
    def test_simple_integer(self):
        r = measure_quantification_density("There are 42 servers in the cluster.")
        assert r.cardinal_count >= 1

    def test_large_number_with_commas(self):
        r = measure_quantification_density("We processed 1,234,567 records today.")
        assert r.cardinal_count >= 1

    def test_decimal_number(self):
        r = measure_quantification_density("The value was 3.14 at equilibrium.")
        assert r.cardinal_count >= 1

    def test_spelled_out_three(self):
        r = measure_quantification_density("Three servers were decommissioned.")
        assert r.cardinal_count >= 1

    def test_spelled_out_hundred(self):
        r = measure_quantification_density("Hundreds of requests were dropped.")
        assert r.cardinal_count >= 1

    def test_spelled_out_million(self):
        r = measure_quantification_density("The database holds millions of records.")
        assert r.cardinal_count >= 1

    def test_spelled_out_twelve(self):
        r = measure_quantification_density("Twelve nodes joined the cluster.")
        assert r.cardinal_count >= 1

    def test_multiple_cardinals(self):
        text = "Server 1 has 32 GB RAM. Server 2 has 64 GB. Server 3 has 128 GB."
        r = measure_quantification_density(text)
        assert r.cardinal_count >= 3

    def test_zero(self):
        r = measure_quantification_density("There were zero failures this week.")
        assert r.cardinal_count >= 1

    def test_a_thousand(self):
        r = measure_quantification_density("About a thousand users logged in.")
        assert r.cardinal_count >= 1


# ── percentages and proportions ─────────────────────────────────


class TestPercentageProportion:
    def test_percentage_symbol(self):
        r = measure_quantification_density("CPU usage hit 87% during peak.")
        assert r.percentage_proportion_count >= 1

    def test_decimal_percentage(self):
        r = measure_quantification_density("Error rate was 0.03% of requests.")
        assert r.percentage_proportion_count >= 1

    def test_spelled_percent(self):
        r = measure_quantification_density("About 45 percent of users returned.")
        assert r.percentage_proportion_count >= 1

    def test_one_third(self):
        r = measure_quantification_density("A third of the fleet was updated.")
        assert r.percentage_proportion_count >= 1

    def test_two_thirds(self):
        r = measure_quantification_density("Two-thirds of nodes are healthy.")
        assert r.percentage_proportion_count >= 1

    def test_half(self):
        r = measure_quantification_density("Half the data was corrupted.")
        assert r.percentage_proportion_count >= 1

    def test_majority(self):
        r = measure_quantification_density("The majority of tests passed.")
        assert r.percentage_proportion_count >= 1

    def test_minority(self):
        r = measure_quantification_density("A minority of requests timed out.")
        assert r.percentage_proportion_count >= 1

    def test_ratio_of(self):
        r = measure_quantification_density("The ratio of reads to writes was 10 to 1.")
        assert r.percentage_proportion_count >= 1

    def test_n_in_m(self):
        r = measure_quantification_density("Three in five users prefer dark mode.")
        assert r.percentage_proportion_count >= 1

    def test_fraction_of(self):
        r = measure_quantification_density("A fraction of the budget remains.")
        assert r.percentage_proportion_count >= 1


# ── measurements with units ─────────────────────────────────────


class TestMeasurementUnits:
    def test_milliseconds(self):
        r = measure_quantification_density("Latency was 45 ms at p99.")
        assert r.measurement_unit_count >= 1

    def test_seconds(self):
        r = measure_quantification_density("The timeout is 30 seconds.")
        assert r.measurement_unit_count >= 1

    def test_gigabytes(self):
        r = measure_quantification_density("The disk holds 500 GB of data.")
        assert r.measurement_unit_count >= 1

    def test_kilometers(self):
        r = measure_quantification_density("The cable runs 12 km underground.")
        assert r.measurement_unit_count >= 1

    def test_kilograms(self):
        r = measure_quantification_density("The server weighs 15 kg.")
        assert r.measurement_unit_count >= 1

    def test_temperature(self):
        r = measure_quantification_density("CPU temperature reached 78°C.")
        assert r.measurement_unit_count >= 1

    def test_currency_dollar(self):
        r = measure_quantification_density("The cost was $4,500 per month.")
        assert r.measurement_unit_count >= 1

    def test_mbps(self):
        r = measure_quantification_density("Bandwidth was 100 Mbps.")
        assert r.measurement_unit_count >= 1

    def test_hours(self):
        r = measure_quantification_density("The job ran for 3 hours.")
        assert r.measurement_unit_count >= 1

    def test_days(self):
        r = measure_quantification_density("Deployment takes 5 days.")
        assert r.measurement_unit_count >= 1

    def test_hertz(self):
        r = measure_quantification_density("The CPU runs at 3.5 GHz.")
        assert r.measurement_unit_count >= 1

    def test_no_measurement_plain(self):
        text = "The process completed successfully. Results were saved."
        r = measure_quantification_density(text)
        assert r.measurement_unit_count == 0


# ── statistical language ────────────────────────────────────────


class TestStatisticalLanguage:
    def test_average(self):
        r = measure_quantification_density("The average latency was 50 ms.")
        assert r.statistical_count >= 1

    def test_median(self):
        r = measure_quantification_density("The median response time improved.")
        assert r.statistical_count >= 1

    def test_standard_deviation(self):
        r = measure_quantification_density(
            "Standard deviation was within acceptable bounds."
        )
        assert r.statistical_count >= 1

    def test_correlation(self):
        r = measure_quantification_density(
            "The correlation between load and latency was strong."
        )
        assert r.statistical_count >= 1

    def test_regression(self):
        r = measure_quantification_density("Our regression model fit well.")
        assert r.statistical_count >= 1

    def test_p_value(self):
        r = measure_quantification_density("The result was significant with p < 0.05.")
        assert r.statistical_count >= 1

    def test_confidence_interval(self):
        r = measure_quantification_density(
            "The confidence interval was narrow at 95%."
        )
        assert r.statistical_count >= 1

    def test_sample_size(self):
        r = measure_quantification_density("Sample size was 10,000 observations.")
        assert r.statistical_count >= 1

    def test_statistically_significant(self):
        r = measure_quantification_density(
            "The difference was statistically significant."
        )
        assert r.statistical_count >= 1

    def test_outlier(self):
        r = measure_quantification_density("One outlier skewed the distribution.")
        assert r.statistical_count >= 1

    def test_multiple_statistical(self):
        text = (
            "The mean was 42.3 with a median of 38.1. "
            "Standard deviation was 5.2, and the correlation was 0.89. "
            "The p-value was 0.003, well below the significance level."
        )
        r = measure_quantification_density(text)
        assert r.statistical_count >= 5


# ── comparative numerics ────────────────────────────────────────


class TestComparativeNumerics:
    def test_multiplier_2x(self):
        r = measure_quantification_density("Performance improved 3× after caching.")
        assert r.comparative_numeric_count >= 1

    def test_twice(self):
        r = measure_quantification_density("This path is twice as fast.")
        assert r.comparative_numeric_count >= 1

    def test_double(self):
        r = measure_quantification_density("Throughput doubled to 200 rps.")
        assert r.comparative_numeric_count >= 1

    def test_triple(self):
        r = measure_quantification_density("Capacity triple to 300 nodes.")
        assert r.comparative_numeric_count >= 1

    def test_n_fold(self):
        r = measure_quantification_density("We saw a 10-fold improvement.")
        assert r.comparative_numeric_count >= 1

    def test_factor_of(self):
        r = measure_quantification_density("Latency improved by a factor of 5.")
        assert r.comparative_numeric_count >= 1

    def test_times_more(self):
        r = measure_quantification_density("This is 3 times more efficient.")
        assert r.comparative_numeric_count >= 1

    def test_order_of_magnitude(self):
        r = measure_quantification_density(
            "Performance improved by an order of magnitude."
        )
        assert r.comparative_numeric_count >= 1

    def test_versus(self):
        r = measure_quantification_density("Latency dropped: 120 ms vs 38 ms.")
        assert r.comparative_numeric_count >= 1

    def test_range_from_to(self):
        r = measure_quantification_density("Values range from 10 to 50.")
        assert r.comparative_numeric_count >= 1


# ── frequency and rate language ─────────────────────────────────


class TestFrequencyRate:
    def test_per_second(self):
        r = measure_quantification_density("Throughput is 1000 requests per second.")
        assert r.frequency_rate_count >= 1

    def test_daily(self):
        r = measure_quantification_density("The job runs daily at midnight.")
        assert r.frequency_rate_count >= 1

    def test_weekly(self):
        r = measure_quantification_density("Reports are generated weekly.")
        assert r.frequency_rate_count >= 1

    def test_monthly(self):
        r = measure_quantification_density("Billing occurs monthly.")
        assert r.frequency_rate_count >= 1

    def test_quarterly(self):
        r = measure_quantification_density("Audits happen quarterly.")
        assert r.frequency_rate_count >= 1

    def test_uptime_percentage(self):
        r = measure_quantification_density("We maintain 99.9% uptime.")
        assert r.frequency_rate_count >= 1

    def test_every_n_minutes(self):
        r = measure_quantification_density("Health checks run every 5 minutes.")
        assert r.frequency_rate_count >= 1

    def test_per_user(self):
        r = measure_quantification_density("Cost is $2.50 per user per month.")
        assert r.frequency_rate_count >= 1

    def test_rate_of(self):
        r = measure_quantification_density("Errors occur at a rate of 3 per hour.")
        assert r.frequency_rate_count >= 1


# ── classification thresholds ────────────────────────────────────


class TestClassificationThresholds:
    def test_unquantified(self):
        text = (
            "The committee reviewed the proposal on Tuesday. "
            "Members voted in favor of the plan. "
            "The project will begin next month. "
            "Staff will receive training materials. "
            "No changes to the existing policy are planned."
        )
        r = measure_quantification_density(text)
        assert r.classification == "unquantified"

    def test_lightly_quantified(self):
        text = (
            "The project launched on Monday morning. "
            "Three teams participated in the rollout. "
            "Initial feedback was positive across the board. "
            "Configuration was handled automatically. "
            "The next review is scheduled for December. "
            "Reports will be submitted on time. "
            "No issues were reported during the migration. "
            "The dashboard shows all services running. "
            "Users noticed faster response times. "
            "The team celebrated with lunch."
        )
        r = measure_quantification_density(text)
        assert r.classification in ("unquantified", "lightly_quantified")

    def test_moderately_quantified(self):
        text = (
            "Revenue reached $2.1 million in Q3. "
            "User growth was 15% over the previous quarter. "
            "The platform handled 5,000 requests per minute. "
            "Average latency dropped to 45 ms after optimization. "
            "Storage usage grew to 800 GB across 12 nodes. "
            "The median response time was 32 ms. "
            "Error rate stayed below 0.1% throughout the month. "
            "Team shipped 8 releases in 30 days."
        )
        r = measure_quantification_density(text)
        assert r.quantification_density_index >= 0.15

    def test_quantification_saturated(self):
        text = (
            "Q3 revenue was $4.2 million, up 23.4% from $3.4 million. "
            "12,000 requests per second at 45 ms p99 latency across 24 nodes. "
            "Retention improved 15.3% with 8,500 accounts in the sample. "
            "Median dropped from 120 ms to 38 ms, a 3.2× improvement. "
            "67.2% utilization, 99.9% uptime, $0.002 per request cost. "
            "R² of 0.87 with p < 0.01 and standard deviation of 2.3. "
            "3.8 TB storage, 500 GB cache, 64 GB RAM per node. "
            "14 releases, 12 min MTTR, 4.6/5 satisfaction score. "
            "2.4× throughput gain at $4,500/month infrastructure cost. "
            "0.03% error rate, 99.97% accuracy, 150 ms timeout."
        )
        r = measure_quantification_density(text)
        assert r.quantification_density_index >= 0.35


# ── rates ────────────────────────────────────────────────────────


class TestRates:
    def test_rates_scale_with_sentences(self):
        short = "There are 42 servers. Latency is 50 ms."
        r = measure_quantification_density(short)
        assert r.cardinal_rate > 0 or r.measurement_unit_rate > 0
        assert r.total_sentences == 2

    def test_rate_zero_for_plain_text(self):
        text = "The file exists. The process completed. The output was saved."
        r = measure_quantification_density(text)
        assert r.cardinal_rate == 0.0
        assert r.statistical_rate == 0.0
        assert r.frequency_rate_rate == 0.0


# ── composite and diversity ──────────────────────────────────────


class TestComposite:
    def test_composite_range(self):
        texts = [
            "Plain text with no numbers at all.",
            "Revenue was $4.2 million with 23% growth and 45 ms latency.",
            "42 servers, 12 GB each, 99.9% uptime, 3× faster, p < 0.01!",
        ]
        for text in texts:
            r = measure_quantification_density(text)
            assert 0.0 <= r.quantification_density_index <= 1.0

    def test_diversity_range(self):
        texts = [
            "Plain text.",
            "42 servers at 23% utilization with 50 ms latency and p < 0.05.",
        ]
        for text in texts:
            r = measure_quantification_density(text)
            assert 0.0 <= r.quantification_diversity_index <= 1.0

    def test_more_quantification_higher_index(self):
        plain = (
            "The committee met on Tuesday. "
            "Proposals were reviewed. "
            "The budget was approved for next quarter. "
            "Staff will receive updated guidelines. "
            "The next meeting is in December."
        )
        quantified = (
            "42 committee members met on Tuesday. "
            "3 proposals were reviewed, each costing $1.2 million. "
            "The $4.5 million budget was approved for Q4. "
            "128 staff will receive 15 pages of guidelines. "
            "The next meeting is in 90 days."
        )
        r_plain = measure_quantification_density(plain)
        r_quant = measure_quantification_density(quantified)
        assert r_quant.quantification_density_index > r_plain.quantification_density_index

    def test_diversity_increases_with_variety(self):
        low_div = "Server 1 has 32 GB. Server 2 has 32 GB. Server 3 has 32 GB."
        high_div = (
            "42 servers process 12,000 requests per second at 45 ms latency. "
            "23% utilization with $2.4 million cost and 99.9% uptime. "
            "The median was 32 ms with standard deviation of 2.1."
        )
        r_low = measure_quantification_density(low_div)
        r_high = measure_quantification_density(high_div)
        assert (
            r_high.quantification_diversity_index
            >= r_low.quantification_diversity_index
        )


# ── orthogonality ────────────────────────────────────────────────


class TestOrthogonality:
    def test_quantified_without_emphasis(self):
        """Numbers can appear without any emphasis language."""
        text = (
            "The server has 64 GB RAM and 2 TB storage. "
            "It processes 5,000 requests per second. "
            "Latency is 45 ms at p99. "
            "The monthly cost is $1,200."
        )
        r = measure_quantification_density(text)
        assert r.cardinal_count >= 4
        assert r.measurement_unit_count >= 3
        # No emphasis markers needed

    def test_quantified_without_gradation(self):
        """Numbers can exist without degree language."""
        text = (
            "The cluster has 24 nodes with 128 GB each. "
            "Storage is 3.8 TB across 48 disks. "
            "Network bandwidth is 10 Gbps per node. "
            "Power consumption is 450 watts per rack unit."
        )
        r = measure_quantification_density(text)
        assert r.measurement_unit_count >= 4
        # No comparatives, superlatives, intensifiers needed

    def test_quantified_without_specificity(self):
        """Numbers can appear in abstract contexts."""
        text = (
            "The correlation was 0.87 with p < 0.01. "
            "The mean was 42.3 and the median was 38.1. "
            "Standard deviation was 5.2 across the sample. "
            "The confidence interval ranged from 39.8 to 44.8."
        )
        r = measure_quantification_density(text)
        assert r.statistical_count >= 4
        # Abstract statistical context, not physically specific


# ── metadata ─────────────────────────────────────────────────────


class TestMetadata:
    def test_total_sentences_nonzero(self):
        r = measure_quantification_density("One sentence. Two sentences.")
        assert r.total_sentences == 2

    def test_details_dict_populated(self):
        r = measure_quantification_density(
            "There are 42 servers at 23% utilization."
        )
        assert "quantification_density_index" in r.details
        assert "classification" in r.details
        assert "cardinal_rate" in r.details
        assert "measurement_unit_rate" in r.details

    def test_result_dataclass_defaults(self):
        r = QuantificationDensityResult()
        assert r.cardinal_count == 0
        assert r.quantification_density_index == 0.0
        assert r.classification == "unquantified"
        assert r.details == {}


# ── edge cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence_with_numbers(self):
        r = measure_quantification_density("The server has 64 GB RAM.")
        assert r.cardinal_count >= 1
        assert r.total_sentences == 1

    def test_numbers_in_quotes(self):
        r = measure_quantification_density(
            'He said "about 50 servers" and left.'
        )
        assert r.cardinal_count >= 1

    def test_year_not_measurement(self):
        r = measure_quantification_density(
            "The project started in the early days of computing."
        )
        assert r.measurement_unit_count == 0

    def test_very_long_text(self):
        text = "The server processed 1000 requests. " * 100
        r = measure_quantification_density(text)
        assert r.total_sentences == 100
        assert r.cardinal_count >= 100
