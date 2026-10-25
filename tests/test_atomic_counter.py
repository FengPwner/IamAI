"""Tests for snippets/atomic_counter.py — crash-safe monotonic counter."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from atomic_counter import AtomicCounter  # noqa: E402


@pytest.fixture
def counter_path(tmp_path: Path) -> Path:
    return tmp_path / "counter.txt"


@pytest.fixture
def counter(counter_path: Path) -> AtomicCounter:
    return AtomicCounter(counter_path)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_fresh_counter_starts_at_zero(self, counter: AtomicCounter) -> None:
        assert counter.value == 0

    def test_reads_existing_value(self, counter_path: Path) -> None:
        counter_path.write_text("42\n", encoding="utf-8")
        c = AtomicCounter(counter_path)
        assert c.value == 42

    def test_empty_file_means_zero(self, counter_path: Path) -> None:
        counter_path.write_text("", encoding="utf-8")
        c = AtomicCounter(counter_path)
        assert c.value == 0

    def test_nonexistent_file_means_zero(self, tmp_path: Path) -> None:
        c = AtomicCounter(tmp_path / "does_not_exist.txt")
        assert c.value == 0

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "a" / "b" / "c" / "counter.txt"
        c = AtomicCounter(p)
        c.increment()
        assert p.exists()


# ---------------------------------------------------------------------------
# increment
# ---------------------------------------------------------------------------


class TestIncrement:
    def test_default_increment_is_one(self, counter: AtomicCounter) -> None:
        assert counter.increment() == 1
        assert counter.increment() == 2
        assert counter.increment() == 3

    def test_custom_delta(self, counter: AtomicCounter) -> None:
        assert counter.increment(10) == 10
        assert counter.increment(5) == 15

    def test_returns_new_value(self, counter: AtomicCounter) -> None:
        result = counter.increment(7)
        assert result == 7
        assert counter.value == 7

    def test_negative_delta_raises(self, counter: AtomicCounter) -> None:
        counter.increment(5)
        with pytest.raises(ValueError, match="negative"):
            counter.increment(-10)

    def test_zero_delta(self, counter: AtomicCounter) -> None:
        counter.increment(3)
        assert counter.increment(0) == 3


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_survives_reopen(self, counter_path: Path) -> None:
        c1 = AtomicCounter(counter_path)
        c1.increment(99)
        del c1

        c2 = AtomicCounter(counter_path)
        assert c2.value == 99

    def test_file_contains_integer(self, counter: AtomicCounter, counter_path: Path) -> None:
        counter.increment(42)
        text = counter_path.read_text(encoding="utf-8").strip()
        assert text == "42"

    def test_no_temp_files_left(self, counter: AtomicCounter, counter_path: Path) -> None:
        counter.increment(5)
        parent = counter_path.parent
        temps = list(parent.glob(f".{counter_path.name}.*.tmp"))
        assert temps == []


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_to_zero(self, counter: AtomicCounter) -> None:
        counter.increment(100)
        counter.reset()
        assert counter.value == 0

    def test_reset_persists(self, counter_path: Path) -> None:
        c1 = AtomicCounter(counter_path)
        c1.increment(50)
        c1.reset()
        del c1

        c2 = AtomicCounter(counter_path)
        assert c2.value == 0

    def test_increment_after_reset(self, counter: AtomicCounter) -> None:
        counter.increment(10)
        counter.reset()
        assert counter.increment() == 1


# ---------------------------------------------------------------------------
# atomicity (best-effort — hard to truly test crash safety in a unit test)
# ---------------------------------------------------------------------------


class TestAtomicity:
    def test_concurrent_increments(self, counter_path: Path) -> None:
        """Multiple threads incrementing should not lose counts."""
        c = AtomicCounter(counter_path)
        n_threads = 8
        n_increments = 100

        def bump() -> None:
            local = AtomicCounter(counter_path)
            for _ in range(n_increments):
                local.increment()

        threads = [threading.Thread(target=bump) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = AtomicCounter(counter_path)
        assert final.value == n_threads * n_increments

    def test_many_sequential_increments(self, counter: AtomicCounter) -> None:
        """Stress test: 1000 increments should yield exactly 1000."""
        for _ in range(1000):
            counter.increment()
        assert counter.value == 1000
