#!/usr/bin/env python3
"""Tests for writer_cognitive_load module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_cognitive_load import (
    CognitiveLoadResult,
    measure_cognitive_load,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_cognitive_load("")
        assert r.cognitive_load_index == 0.0
        assert r.classification == "breezy"

    def test_whitespace_only(self):
        r = measure_cognitive_load("   \n\n   ")
        assert r.cognitive_load_index == 0.0

    def test_single_word(self):
        r = measure_cognitive_load("Hello.")
        assert r.classification == "breezy"

    def test_no_load_plain_sentence(self):
        r = measure_cognitive_load("The sun is bright today.")
        assert r.total_markers <= 1
        assert r.cognitive_load_index < 0.10


# ── breezy prose (very low cognitive load) ─────────────────────


class TestBreezy:
    def test_childrens_book_style(self):
        text = "The dog ran. The cat sat. The bird sang. They were happy."
        r = measure_cognitive_load(text)
        assert r.classification == "breezy"
        assert r.cognitive_load_index < 0.10

    def test_simple_instructions(self):
        text = (
            "Open the box. Take out the parts. "
            "Place the base on the table. Insert the battery."
        )
        r = measure_cognitive_load(text)
        assert r.classification in ("breezy", "accessible")
        assert r.cognitive_load_index < 0.25

    def test_short_declarative_paragraph(self):
        text = (
            "Water boils at 100 degrees Celsius. "
            "Ice melts at 0 degrees. "
            "Steam rises from hot water."
        )
        r = measure_cognitive_load(text)
        assert r.embedding_count == 0 or r.embedding_score < 0.1
        assert r.classification in ("breezy", "accessible")


# ── accessible prose (low cognitive load) ───────────────────────


class TestAccessible:
    def test_news_style(self):
        text = (
            "The mayor announced the new policy on Monday. "
            "It will affect all public schools in the district. "
            "Parents expressed mixed reactions. "
            "Some praised the initiative while others raised concerns."
        )
        r = measure_cognitive_load(text)
        assert r.cognitive_load_index < 0.40

    def test_blog_style(self):
        text = (
            "If you want to improve your code, start with tests. "
            "They help you catch bugs early. "
            "Writing tests also forces you to think about edge cases."
        )
        r = measure_cognitive_load(text)
        assert r.cognitive_load_index >= 0.0
        assert r.left_branching_count >= 1  # "If you want..."


# ── moderate prose ──────────────────────────────────────────────


class TestModerate:
    def test_technical_blog(self):
        text = (
            "The function, which was introduced to handle edge cases, "
            "accepts a callback that determines how results are filtered. "
            "Although it performs well in most scenarios, "
            "the algorithm that underlies the sorting mechanism "
            "has a worst-case complexity of O(n²)."
        )
        r = measure_cognitive_load(text)
        assert r.embedding_count >= 2
        assert r.cognitive_load_index >= 0.10

    def test_pronoun_heavy_text(self):
        text = (
            "Alice met Bob at the conference. "
            "He showed her his project. "
            "She told him that it was impressive. "
            "They discussed how they could collaborate on it."
        )
        r = measure_cognitive_load(text)
        assert r.referential_count >= 4
        assert r.referential_score > 0.0


# ── demanding prose ─────────────────────────────────────────────


class TestDemanding:
    def test_legal_document(self):
        text = (
            "Notwithstanding the provisions set forth in Section 3(a), "
            "which govern the allocation of risk between the parties, "
            "and having regard to the obligations imposed by applicable law, "
            "the Licensee, subject to the conditions specified herein, "
            "shall indemnify the Licensor against all claims, "
            "which may arise as a result of the Licensee's use of the Software, "
            "provided that such claims are not caused by the Licensor's negligence."
        )
        r = measure_cognitive_load(text)
        assert r.embedding_count >= 3
        assert r.cognitive_load_index >= 0.15
        assert r.total_sentences <= 3

    def test_academic_abstract(self):
        text = (
            "This study investigates the extent to which socioeconomic factors, "
            "which include household income, parental education level, "
            "and neighborhood quality, influence academic achievement "
            "among adolescents who attended public schools in urban areas "
            "during the period spanning 2010 to 2020, "
            "while controlling for demographic variables such as age, "
            "gender, and ethnicity."
        )
        r = measure_cognitive_load(text)
        assert r.embedding_count >= 2
        assert r.cognitive_load_index >= 0.15
        assert r.total_words > 40


# ── strenuous prose ─────────────────────────────────────────────


class TestStrenuous:
    def test_garden_path_nesting(self):
        text = (
            "The hypothesis that the observation that the specimen "
            "which the researcher who the committee that the university "
            "appointed selected had contaminated was correct surprised everyone. "
            "Having been warned that the procedure, which, although approved, "
            "was considered risky, might fail, and despite the fact that "
            "alternatives, which were both cheaper and safer, existed, "
            "the team, which had invested months of preparation, proceeded."
        )
        r = measure_cognitive_load(text)
        assert r.embedding_count >= 6
        assert r.cognitive_load_index >= 0.25

    def test_heavy_left_branching(self):
        text = (
            "Having reviewed the documentation, which spans three volumes, "
            "and after consulting with the advisory board, "
            "which was assembled specifically for this purpose, "
            "the committee reached its conclusion. "
            "Not only was the proposal rejected, "
            "but the entire funding mechanism, "
            "which had been in place since 2015, was dismantled."
        )
        r = measure_cognitive_load(text)
        assert r.left_branching_count >= 1
        assert r.embedding_count >= 4


# ── channel-specific tests ──────────────────────────────────────


class TestEmbeddingDepth:
    def test_parenthetical(self):
        text = "The result (which was unexpected) changed everything."
        r = measure_cognitive_load(text)
        assert r.embedding_count >= 2  # paren + which

    def test_no_embedding(self):
        text = "She walked to the store. She bought milk. She went home."
        r = measure_cognitive_load(text)
        assert r.embedding_count == 0

    def test_relative_clause_chain(self):
        text = (
            "The book that the author who won the prize "
            "that the committee established wrote is popular."
        )
        r = measure_cognitive_load(text)
        assert r.embedding_count >= 3


class TestReferentialDistance:
    def test_heavy_pronouns(self):
        text = (
            "He told her that it was fine. "
            "She showed him this. "
            "They looked at those."
        )
        r = measure_cognitive_load(text)
        assert r.referential_count >= 5

    def test_anaphoric_phrases(self):
        text = (
            "The former approach is slow. "
            "The latter is fast. "
            "As mentioned above, speed matters. "
            "As noted earlier, cost is also a factor."
        )
        r = measure_cognitive_load(text)
        assert r.referential_count >= 4


class TestConceptualDensity:
    def test_technical_terms(self):
        text = (
            "The API uses OAuth2 for authentication. "
            "The JWT tokens are validated by the middleware. "
            "HTTPS ensures transport security."
        )
        r = measure_cognitive_load(text)
        assert r.conceptual_count >= 2  # API, OAuth2, JWT, HTTPS

    def test_concept_introducers(self):
        text = (
            'A technique known as "gradient descent" is used for optimization. '
            "The learning rate, referred to as alpha, controls step size. "
            "This process is termed convergence."
        )
        r = measure_cognitive_load(text)
        assert r.conceptual_count >= 3


class TestSyntacticBranching:
    def test_left_branching(self):
        text = (
            "Having finished the analysis, the team published the results. "
            "Although the data was incomplete, the conclusions held. "
            "If the hypothesis is correct, we should see a correlation."
        )
        r = measure_cognitive_load(text)
        assert r.left_branching_count >= 2

    def test_right_branching(self):
        text = (
            "The team published the results after finishing the analysis. "
            "The conclusions held although the data was incomplete. "
            "We should see a correlation if the hypothesis is correct."
        )
        r = measure_cognitive_load(text)
        assert r.left_branching_count <= 1

    def test_fronted_adjunct(self):
        text = (
            "In the early morning hours, the server crashed. "
            "During the maintenance window, the team applied patches."
        )
        r = measure_cognitive_load(text)
        assert r.left_branching_count >= 2


class TestWorkingMemory:
    def test_parenthetical_burden(self):
        text = (
            "The algorithm (specifically the sorting step) "
            "requires O(n log n) time. "
            "The data structure (a balanced BST) supports fast lookup."
        )
        r = measure_cognitive_load(text)
        assert r.working_memory_count >= 2

    def test_interrupted_constituent(self):
        text = "The result — as everyone expected — was negative."
        r = measure_cognitive_load(text)
        assert r.working_memory_count >= 1

    def test_unmatched_parens(self):
        text = "The function accepts (two parameters."
        r = measure_cognitive_load(text)
        # unmatched paren adds extra burden
        assert r.working_memory_count >= 2


# ── composite and classification ────────────────────────────────


class TestComposite:
    def test_index_range(self):
        """Index must always be in [0.0, 1.0]."""
        texts = [
            "Simple.",
            "A" * 500 + "." + "B" * 500 + ".",
            "Having been told that the process which was running since Monday "
            "had failed, the administrator, who was on call, restarted it.",
            "",
            "Hello world.",
        ]
        for t in texts:
            r = measure_cognitive_load(t)
            assert 0.0 <= r.cognitive_load_index <= 1.0

    def test_classification_ordering(self):
        """Higher load texts should get harder classifications."""
        breezy = measure_cognitive_load("The dog ran. The cat sat.")
        heavy = measure_cognitive_load(
            "Notwithstanding the provisions which govern the allocation "
            "of risk between the parties, and having regard to the obligations "
            "which are imposed by applicable law, the Licensee, "
            "subject to the conditions which are specified herein, "
            "shall indemnify the Licensor against all claims "
            "which may arise as a result of the use."
        )
        assert breezy.cognitive_load_index < heavy.cognitive_load_index

    def test_classification_values(self):
        """Classification must be one of the valid labels."""
        valid = {"breezy", "accessible", "moderate", "demanding", "strenuous"}
        texts = [
            "",
            "Hello.",
            "The dog that barked loudly ran away quickly.",
            "Having reviewed the report, which contained numerous errors, "
            "the committee decided to reject the proposal.",
            "Not only was the system, which had been designed to handle "
            "millions of requests, overwhelmed by the traffic, "
            "but the backup servers, which were supposed to activate "
            "automatically, failed to respond.",
        ]
        for t in texts:
            r = measure_cognitive_load(t)
            assert r.classification in valid

    def test_orthogonal_to_length(self):
        """Short text can have higher load than long text."""
        short_dense = (
            "The rat the cat the dog chased caught ate the malt."
        )
        long_simple = (
            "The sun rose. Birds sang. Children played in the park. "
            "Families ate lunch. Dogs chased balls. The day was warm. "
            "Everyone smiled. Ice cream melted slowly. "
            "Clouds drifted overhead. The breeze was gentle."
        )
        r_short = measure_cognitive_load(short_dense)
        r_long = measure_cognitive_load(long_simple)
        # Short embedded text should score higher per-sentence
        assert r_short.embedding_score >= r_long.embedding_score


# ── metadata ────────────────────────────────────────────────────


class TestMetadata:
    def test_word_count(self):
        r = measure_cognitive_load("one two three four five.")
        assert r.total_words == 5

    def test_sentence_count(self):
        r = measure_cognitive_load("First sentence. Second sentence. Third.")
        assert r.total_sentences == 3

    def test_total_markers_sum(self):
        text = (
            "The function which accepts a callback "
            "(specifically a filter function) returns a list."
        )
        r = measure_cognitive_load(text)
        expected = (
            r.embedding_count
            + r.referential_count
            + r.conceptual_count
            + r.left_branching_count
            + r.working_memory_count
        )
        assert r.total_markers == expected
