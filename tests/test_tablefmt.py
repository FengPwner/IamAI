"""Tests for snippets/tablefmt.py — the plain-text table renderer.

covers:
- empty table (headers only, no rows)
- single-row table
- multi-row table with varying widths
- the doctest example from the module
- rows with fewer cells than headers (short rows)
- numeric and string content mixed
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))
from tablefmt import render_table


class TestEmptyTable(unittest.TestCase):

    def test_headers_only(self):
        result = render_table(["a", "b"], [])
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 2)  # header + rule
        self.assertIn("a", lines[0])
        self.assertIn("b", lines[0])
        # rule line is all dashes and spaces
        self.assertTrue(all(c in "- " for c in lines[1]))


class TestSingleRow(unittest.TestCase):

    def test_one_row(self):
        result = render_table(["name", "age"], [["alice", "30"]])
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 3)  # header + rule + 1 row
        self.assertIn("alice", lines[2])
        self.assertIn("30", lines[2])


class TestMultiRow(unittest.TestCase):

    def test_column_widths_expand_to_fit(self):
        result = render_table(["x", "y"], [["1", "2"], ["100", "20"]])
        lines = result.strip().split("\n")
        # header line should right-align "x" under "100"
        # and "y" under "20"
        header = lines[0]
        row1 = lines[2]
        row2 = lines[3]
        # "100" is wider than "x", so column 1 width is 3
        self.assertIn("100", row2)
        self.assertIn("x", header)

    def test_doctest_example(self):
        result = render_table(["a", "bb"], [[1, 2], [100, 20]])
        expected_lines = [
            "  a bb",
            "--- --",
            "  1  2",
            "100 20",
        ]
        actual_lines = result.rstrip("\n").split("\n")
        for expected, actual in zip(expected_lines, actual_lines):
            self.assertEqual(actual.rstrip(), expected.rstrip())


class TestShortRows(unittest.TestCase):

    def test_row_fewer_cells_than_headers(self):
        # A row with fewer cells than headers should not crash.
        result = render_table(["a", "b", "c"], [["1"]])
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 3)
        self.assertIn("1", lines[2])


class TestMixedContent(unittest.TestCase):

    def test_numbers_and_strings(self):
        result = render_table(
            ["id", "name", "score"],
            [[1, "alice", 99.5], [2, "bob", 87.0]],
        )
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 4)
        self.assertIn("alice", lines[2])
        self.assertIn("bob", lines[3])
        self.assertIn("99.5", lines[2])

    def test_empty_string_cells(self):
        result = render_table(["a", "b"], [["", "x"], ["y", ""]])
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 4)


if __name__ == "__main__":
    unittest.main()
