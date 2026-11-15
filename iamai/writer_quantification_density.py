#!/usr/bin/env python3
"""writer_quantification_density — measure how much prose leans on numbers.

Numbers are the prose of certainty.  "Several people complained" is a
claim; "47 people complained" is evidence.  "Revenue grew significantly"
is an opinion; "revenue grew 23.4% year-over-year" is a fact wearing
a decimal point.  Quantification transforms the subjective into the
auditable, the arguable into the verifiable.

But numbers are also a rhetorical choice.  Some writers saturate their
prose with measurements — every claim carries a statistic, every
observation comes with a percentage.  Others avoid numbers entirely,
preferring qualitative description.  A text's quantification density
reveals its relationship to empirical evidence: whether the writer
trusts the reader to handle numbers, whether the domain supports
measurement, whether precision is valued over impression.

Quantification operates through several distinct channels.
**Cardinal numbers** state quantities directly: "three servers",
"12 requests", "one failure".  **Percentages and proportions**
express ratios: "23% of users", "a third of requests",
"the majority".  **Measurements with units** anchor numbers to
physical or temporal reality: "250 ms latency", "3.2 GB",
"14 days", "200°C".  **Statistical language** invokes the
machinery of analysis: "average", "median", "correlation",
"p-value", "standard deviation", "confidence interval",
"regression".  **Comparative numerics** use numbers to rank
or contrast: "twice as fast", "3× improvement", "a factor of
ten", "an order of magnitude".  **Frequency and rate language**
express temporal quantification: "per second", "daily",
"every 15 minutes", "99.9% uptime", "once per quarter".

A text's quantification density reveals its genre and intent.
Scientific papers are dense with numbers — every finding carries
a p-value, every sample a count.  Financial reports live in
quantification — revenue, margin, growth rate, EBITDA.  Technical
documentation sprinkles numbers at parameters — timeouts, limits,
defaults, thresholds.  Marketing uses numbers selectively —
"10× faster", "99.9% uptime", "$0 to start".  Literary prose
avoids quantification entirely — "she waited a long time" never
becomes "she waited 47 minutes".  Journalism mixes numbers with
narrative — "the 3-year plan affected 2 million residents".
Casual writing approximates — "a bunch", "tons", "a lot".

This module measures **how frequently, how diversely, and through
what channels a text deploys numerical and statistical language**
— cardinal numbers, percentages, measurements, statistical terms,
comparative numerics, and frequency/rate expressions.

Orthogonality to other metrics
-------------------------------

- **specificity** tracks how detailed and concrete the prose is.
  Specificity can be achieved without numbers ("the red brick
  building on 5th Avenue") and numbers can appear in vague prose
  ("about 100 or so things happened").  Specificity is about
  detail; quantification is about measurement.  A text can be
  specific and unquantified ("she wore a blue scarf") or
  quantified and unspecific ("approximately N items were processed").

- **concreteness** tracks physical, sensory, tangible language.
  "The 3 kg weight" is both concrete and quantified; "the
  statistical correlation was 0.87" is quantified but abstract;
  "the heavy stone" is concrete but unquantified.  Concreteness
  is about tangibility; quantification is about numerability.

- **gradation_density** tracks degree language — comparatives,
  superlatives, intensifiers.  "Much larger" uses gradation;
  "3.2× larger" uses quantification.  "Very fast" gradates;
  "250 ms" quantifies.  Gradation calibrates intensity on a
  subjective scale; quantification anchors to an objective one.
  A text can use both ("significantly faster at 12 ms vs 45 ms")
  or neither ("the fast path").

- **precision** tracks exactness of expression.  Precision can be
  linguistic ("the authentication middleware" vs "the thing that
  checks login") without being numerical.  Quantification is one
  form of precision but not the only one.  "Around 50" is
  quantified but imprecise; "exactly the third item from the left"
  is precise but not numerical.

- **emphasis_density** tracks attention-direction.  Numbers can
  emphasize ("the **47** failures" spotlights the count) but
  emphasis can exist without numbers ("the **critical** failure").
  Emphasis directs attention; quantification provides measurable
  evidence.  The number 99.9% can be emphasized or stated flatly.

- **formality** tracks register.  Quantification appears in both
  formal ("the regression coefficient was 0.34") and informal
  ("I've told you like 50 times") prose.  Formality is about
  tone; quantification is about measurement.

Quantification density asks: **how much of the prose is built on
numerical scaffolding, and what does the distribution of cardinals,
percentages, measurements, statistics, comparative numerics, and
frequency language reveal about the writer's relationship to
empirical evidence?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── cardinal numbers ────────────────────────────────────────────
# Digit sequences (with optional comma separators) and common
# spelled-out numbers that serve as quantifiers in prose.
_CARDINAL = re.compile(
    r"(?:"
    # digit sequences: 42, 1000, 1,000, 3.14, 0.001
    r"\b\d+(?:,\d{3})*(?:\.\d+)?\b|"
    # spelled-out cardinals (common small numbers in prose)
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|a\s+hundred|a\s+thousand|a\s+million|"
    r"a\s+billion|hundreds?|thousands?|millions?|billions?)\b"
    r")",
    re.IGNORECASE,
)

# ── percentages and proportions ─────────────────────────────────
_PERCENTAGE_PROPORTION = re.compile(
    r"(?:"
    # percentage: 23%, 4.5%, 100%
    r"\d+(?:\.\d+)?\s*%|"
    # spelled out: percent, percentage
    r"\b\d+(?:\.\d+)?\s+percent\b|"
    r"\bpercentage\b|"
    # proportion language
    r"\b(?:a\s+)?(?:third|quarter|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"half|two-thirds|three-quarters|four-fifths)\b|"
    r"\b(?:majority|minority|plurality)\b|"
    r"\b(?:a\s+)?(?:fraction|ratio|proportion|share)\s+(?:of|between)\b|"
    r"\b\d+\s+in\s+\d+\b|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+in\s+"
    r"(?:two|three|four|five|six|seven|eight|nine|ten)\b"
    r")",
    re.IGNORECASE,
)

# ── measurements with units ─────────────────────────────────────
_MEASUREMENT_UNIT = re.compile(
    r"(?:"
    # time: ms, s, sec, min, hr, hours, days, weeks, months, years
    r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|sec|seconds?|min|minutes?|"
    r"hr|hours?|days?|weeks?|months?|years?|decades?|centuries)\b|"
    # size: bytes, KB, MB, GB, TB, PB
    r"\b\d+(?:\.\d+)?\s*(?:bytes?|[KMGTP]B|KiB|MiB|GiB|TiB|PiB|"
    r"kilobytes?|megabytes?|gigabytes?|terabytes?)\b|"
    # distance: km, m, cm, mm, mi, ft, in, inches
    r"\b\d+(?:\.\d+)?\s*(?:km|kilometers?|meters?|m|cm|mm|"
    r"miles?|mi|feet|ft|inches?|in|yards?|yd)\b|"
    # weight: kg, g, mg, lb, oz, tons
    r"\b\d+(?:\.\d+)?\s*(?:kg|kilograms?|grams?|g|mg|milligrams?|"
    r"pounds?|lbs?|ounces?|oz|tons?|tonnes?)\b|"
    # temperature: °C, °F, K
    r"\b\d+(?:\.\d+)?\s*°[CFK]\b|"
    r"\b\d+(?:\.\d+)?\s*(?:degrees?\s+(?:Celsius|Fahrenheit|Kelvin))\b|"
    # frequency: Hz, kHz, MHz, GHz
    r"\b\d+(?:\.\d+)?\s*(?:Hz|kHz|MHz|GHz)\b|"
    # speed: km/h, mph, m/s
    r"\b\d+(?:\.\d+)?\s*(?:km/h|mph|m/s|knots?)\b|"
    # power: W, kW, MW, GW, watts
    r"\b\d+(?:\.\d+)?\s*(?:[kKMG]?[Ww](?:atts?)?|watts?)\b|"
    # data rate: Mbps, Gbps, Kbps, bps
    r"\b\d+(?:\.\d+)?\s*(?:[KMGTP]?bps|bits?/s)\b|"
    # currency: $, €, £, ¥ + digits
    r"[$€£¥]\s*\d+(?:[,.]\d+)?|"
    r"\b\d+(?:\.\d+)?\s*(?:USD|EUR|GBP|JPY|CNY|dollars?|euros?|pounds?|yen)\b"
    r")",
    re.IGNORECASE,
)

# ── statistical language ────────────────────────────────────────
_STATISTICAL = re.compile(
    r"\b(?:"
    # descriptive statistics
    r"average|mean|median|mode|midpoint|"
    # spread
    r"standard\s+deviation|variance|range|"
    r"(?:inter)?quartile|percentile|"
    # correlation and regression
    r"correlation|regression|r-squared|R²|"
    r"coefficient|slope|intercept|"
    # significance
    r"p-value|p\s*(?:<|>|=|≤|≥)\s*0?\.\d+|"
    r"confidence\s+interval|significance\s+level|"
    r"statistically\s+significant|"
    r"null\s+hypothesis|alternative\s+hypothesis|"
    # distribution
    r"distribution|normal\s+distribution|gaussian|"
    r"bell\s+curve|outlier|skew(?:ness|ed)?|kurtosis|"
    # sampling
    r"sample\s+size|population|margin\s+of\s+error|"
    r"(?:random\s+)?sampling|cohort|"
    # comparison
    r"t-test|chi-square|anova|manova|"
    r"effect\s+size|odds\s+ratio|relative\s+risk|"
    r"hazard\s+ratio"
    r")\b",
    re.IGNORECASE,
)

# ── comparative numerics ────────────────────────────────────────
_COMPARATIVE_NUMERIC = re.compile(
    r"(?:"
    # multiplier: 2×, 3x, 10×, N-fold
    r"\b\d+\s*[×xX](?:\s|[,.;:!?]|$)|"
    r"\b\d+-fold\b|"
    r"\b(?:twice|thrice|doubled?|tripled?|quadrupled?|tenfold|hundredfold)\b|"
    # factor language
    r"\b(?:a\s+)?factor\s+of\s+\d+\b|"
    r"\b\d+\s+times?\s+(?:as|more|less|faster|slower|larger|smaller|higher|lower)\b|"
    # order of magnitude
    r"\border\s+of\s+magnitude\b|"
    r"\b(?:one|two|three)\s+orders?\s+of\s+magnitude\b|"
    # explicit numeric comparison (with optional unit words)
    r"\b\d+(?:\.\d+)?\s*(?:\w+\s+)?(?:vs?\.?|versus)\s*\d+(?:\.\d+)?\b|"
    # range
    r"\b(?:from\s+)?\d+(?:\.\d+)?\s*(?:to|–|-)\s*\d+(?:\.\d+)?\b"
    r")",
    re.IGNORECASE,
)

# ── frequency and rate language ─────────────────────────────────
_FREQUENCY_RATE = re.compile(
    r"(?:"
    # per-unit: per second, per day, per user
    r"\bper\s+(?:second|minute|hour|day|week|month|year|user|request|"
    r"session|item|event|transaction|connection|thread|core|node)\b|"
    # slash rates: req/s, ops/sec, fps
    r"\b\w+/(?:s|sec|min|hr|h|day)\b|"
    # frequency adverbs with numeric context
    r"\b(?:daily|weekly|monthly|quarterly|annually|yearly|hourly)\b|"
    # uptime / availability
    r"\b\d+(?:\.\d+)?%\s*(?:uptime|availability|reliability|accuracy|"
    r"precision|recall|throughput|success\s+rate)\b|"
    # every N units
    r"\bevery\s+\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?)\b|"
    # rate phrases
    r"\bat\s+(?:a\s+)?(?:rate\s+of|the\s+rate\s+of)\s+\d+|"
    r"\b\d+\s+(?:per|every)\s+\d+\b"
    r")",
    re.IGNORECASE,
)

# ── unique quantification forms ─────────────────────────────────
_ALL_QUANT_FORMS = re.compile(
    r"(?:"
    r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|"
    r"\b\d+(?:\.\d+)?\s*%|"
    r"\b\d+(?:\.\d+)?\s*(?:ms|seconds?|minutes?|hours?|days?|weeks?|"
    r"months?|years?|[KMGTP]B|km|miles?|kg|pounds?)\b|"
    r"\b(?:average|mean|median|correlation|regression|p-value)\b"
    r")",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class QuantificationDensityResult:
    """Results of quantification density analysis."""

    # Raw counts
    cardinal_count: int = 0
    percentage_proportion_count: int = 0
    measurement_unit_count: int = 0
    statistical_count: int = 0
    comparative_numeric_count: int = 0
    frequency_rate_count: int = 0
    unique_quant_forms: int = 0

    # Rates per 100 sentences
    cardinal_rate: float = 0.0
    percentage_proportion_rate: float = 0.0
    measurement_unit_rate: float = 0.0
    statistical_rate: float = 0.0
    comparative_numeric_rate: float = 0.0
    frequency_rate_rate: float = 0.0

    # Composite
    quantification_diversity_index: float = 0.0
    quantification_density_index: float = 0.0
    classification: str = "unquantified"

    # Metadata
    total_sentences: int = 0
    details: dict = field(default_factory=dict)


# ── helper functions ────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences (approximate)."""
    stripped = text.strip()
    if not stripped:
        return 0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    return max(len(sentences), 1)


def _count_matches(pattern: re.Pattern, text: str) -> int:
    """Count non-overlapping regex matches."""
    return len(pattern.findall(text))


# ── main function ───────────────────────────────────────────────


def measure_quantification_density(text: str) -> QuantificationDensityResult:
    """Analyze quantification density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    QuantificationDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = QuantificationDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    cardinal = _count_matches(_CARDINAL, text)
    pct_prop = _count_matches(_PERCENTAGE_PROPORTION, text)
    measurement = _count_matches(_MEASUREMENT_UNIT, text)
    statistical = _count_matches(_STATISTICAL, text)
    comp_numeric = _count_matches(_COMPARATIVE_NUMERIC, text)
    freq_rate = _count_matches(_FREQUENCY_RATE, text)

    # Unique quantification forms for diversity
    all_forms = _ALL_QUANT_FORMS.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.cardinal_count = cardinal
    result.percentage_proportion_count = pct_prop
    result.measurement_unit_count = measurement
    result.statistical_count = statistical
    result.comparative_numeric_count = comp_numeric
    result.frequency_rate_count = freq_rate
    result.unique_quant_forms = len(unique_forms)

    # Rates per 100 sentences
    result.cardinal_rate = round(cardinal * scale, 3)
    result.percentage_proportion_rate = round(pct_prop * scale, 3)
    result.measurement_unit_rate = round(measurement * scale, 3)
    result.statistical_rate = round(statistical * scale, 3)
    result.comparative_numeric_rate = round(comp_numeric * scale, 3)
    result.frequency_rate_rate = round(freq_rate * scale, 3)

    # Diversity: ratio of unique forms to max expected (~20)
    max_possible_forms = 20
    result.quantification_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    cap_cardinal = min(1.0, result.cardinal_rate / 30.0)
    cap_pct = min(1.0, result.percentage_proportion_rate / 10.0)
    cap_measurement = min(1.0, result.measurement_unit_rate / 15.0)
    cap_statistical = min(1.0, result.statistical_rate / 8.0)
    cap_comp = min(1.0, result.comparative_numeric_rate / 8.0)
    cap_freq = min(1.0, result.frequency_rate_rate / 6.0)
    cap_diversity = result.quantification_diversity_index

    composite = (
        0.20 * cap_cardinal
        + 0.15 * cap_pct
        + 0.15 * cap_measurement
        + 0.12 * cap_statistical
        + 0.10 * cap_comp
        + 0.08 * cap_freq
        + 0.20 * cap_diversity
    )
    result.quantification_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.quantification_density_index
    if idx < 0.05:
        result.classification = "unquantified"
    elif idx < 0.15:
        result.classification = "lightly_quantified"
    elif idx < 0.35:
        result.classification = "moderately_quantified"
    elif idx < 0.60:
        result.classification = "heavily_quantified"
    else:
        result.classification = "quantification_saturated"

    result.details = {
        "cardinal_rate": result.cardinal_rate,
        "percentage_proportion_rate": result.percentage_proportion_rate,
        "measurement_unit_rate": result.measurement_unit_rate,
        "statistical_rate": result.statistical_rate,
        "comparative_numeric_rate": result.comparative_numeric_rate,
        "frequency_rate_rate": result.frequency_rate_rate,
        "quantification_diversity_index": result.quantification_diversity_index,
        "quantification_density_index": result.quantification_density_index,
        "classification": result.classification,
    }

    return result


# ── CLI convenience ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    r = measure_quantification_density(text)
    print(f"quantification_density_index : {r.quantification_density_index:.4f}")
    print(f"classification               : {r.classification}")
    print(f"cardinal_rate                : {r.cardinal_rate}")
    print(f"percentage_proportion_rate   : {r.percentage_proportion_rate}")
    print(f"measurement_unit_rate        : {r.measurement_unit_rate}")
    print(f"statistical_rate             : {r.statistical_rate}")
    print(f"comparative_numeric_rate     : {r.comparative_numeric_rate}")
    print(f"frequency_rate_rate          : {r.frequency_rate_rate}")
    print(f"quantification_diversity     : {r.quantification_diversity_index}")
    print(f"total_sentences              : {r.total_sentences}")
