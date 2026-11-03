"""Tests for iamai.writer_freeze — pause/stabilize/resume for git ops."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from iamai.writer_freeze import (
    is_writer_paused,
    wait_for_stable_tree,
    writer_freeze,
)


# ---------------------------------------------------------------------------
# wait_for_stable_tree
# ---------------------------------------------------------------------------

class TestWaitForStableTree:
    """The tree-stabilizer should return True when consecutive reads match."""

    def test_stable_tree_returns_true(self, tmp_path):
        """A git repo with no changes produces the same empty snapshot twice."""
        _init_git(tmp_path)
        result = wait_for_stable_tree(tmp_path, settle=0.05, timeout=2.0)
        assert result is True

    def test_timeout_returns_false(self, tmp_path):
        """If the tree keeps changing, we eventually give up."""
        _init_git(tmp_path)
        counter = {"n": 0}

        def flaky_snapshot(repo):
            counter["n"] += 1
            return f" M file_{counter['n']}.txt"

        with patch("iamai.writer_freeze._tree_snapshot", side_effect=flaky_snapshot):
            result = wait_for_stable_tree(tmp_path, settle=0.01, timeout=0.1)
        assert result is False
        assert counter["n"] >= 2

    def test_stabilizes_after_transient_change(self, tmp_path):
        """One change then stability should still return True."""
        _init_git(tmp_path)
        snapshots = iter(["M data/foo.json", "M data/foo.json", "M data/foo.json"])

        with patch("iamai.writer_freeze._tree_snapshot", side_effect=snapshots):
            result = wait_for_stable_tree(tmp_path, settle=0.01, timeout=5.0)
        assert result is True


# ---------------------------------------------------------------------------
# is_writer_paused
# ---------------------------------------------------------------------------

class TestIsWriterPaused:
    """Check the pause-file existence probe."""

    def test_not_paused_by_default(self):
        """No pause file means the writer is running."""
        with _temp_pause_file("test-freeze-a"):
            pass  # file created then removed
        assert is_writer_paused("test-freeze-a") is False

    def test_paused_when_file_exists(self):
        """Pause file present means the writer is frozen."""
        with _temp_pause_file("test-freeze-b") as pf:
            pf.touch()
            assert is_writer_paused("test-freeze-b") is True
        # cleanup: file removed on context exit
        assert is_writer_paused("test-freeze-b") is False


# ---------------------------------------------------------------------------
# writer_freeze context manager
# ---------------------------------------------------------------------------

class TestWriterFreeze:
    """The context manager should pause, stabilize, yield, and resume."""

    def test_creates_and_removes_pause_file(self, tmp_path):
        """Pause file should exist inside the context and not after."""
        _init_git(tmp_path)
        writer_id = "test-freeze-c"
        pf = _pause_path(writer_id)

        with writer_freeze(writer_id, repo=tmp_path, settle=0.05, timeout=2.0) as info:
            assert pf.exists(), "pause file should exist during freeze"
            assert info["paused"] is True
            assert info["stable"] is True
            assert info["settled_in"] >= 0

        assert not pf.exists(), "pause file should be removed after thaw"

    def test_preserves_pre_existing_pause_file(self, tmp_path):
        """If the pause file already existed, don't delete it on exit."""
        _init_git(tmp_path)
        writer_id = "test-freeze-d"
        pf = _pause_path(writer_id)
        pf.touch()  # simulate test-gate pause

        with writer_freeze(writer_id, repo=tmp_path, settle=0.05, timeout=2.0):
            assert pf.exists()

        assert pf.exists(), "pre-existing pause file must not be removed"
        pf.unlink(missing_ok=True)  # cleanup

    def test_removes_pause_on_exception(self, tmp_path):
        """Even if the body raises, the pause file must be cleaned up."""
        _init_git(tmp_path)
        writer_id = "test-freeze-e"
        pf = _pause_path(writer_id)

        with pytest.raises(ValueError):
            with writer_freeze(writer_id, repo=tmp_path, settle=0.05, timeout=2.0):
                assert pf.exists()
                raise ValueError("simulated failure")

        assert not pf.exists(), "pause file must be removed even on exception"

    def test_yield_info_contains_diagnostics(self, tmp_path):
        """The yielded dict should have paused, stable, and settled_in keys."""
        _init_git(tmp_path)
        writer_id = "test-freeze-f"

        with writer_freeze(writer_id, repo=tmp_path, settle=0.05, timeout=2.0) as info:
            assert set(info.keys()) == {"paused", "stable", "settled_in"}
            assert isinstance(info["settled_in"], float)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _init_git(path: Path) -> None:
    """Create a minimal git repo for testing."""
    import subprocess
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path, capture_output=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
    )


@contextmanager
def _temp_pause_file(writer_id: str):
    """Create and auto-cleanup a pause file for testing."""
    pf = _pause_path(writer_id)
    try:
        yield pf
    finally:
        pf.unlink(missing_ok=True)


def _pause_path(writer_id: str) -> Path:
    return Path("/tmp") / f"iamai-writer-pause-{writer_id}"


