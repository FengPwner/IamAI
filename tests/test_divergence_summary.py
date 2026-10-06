"""Tests for push_guard.divergence_summary — visit 40 addition.

Each test patches the low-level git helpers so we don't need a real repo.
The summary function is a thin wrapper over divergence_info, so these
tests focus on the string formatting and edge cases.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

MODULE = "iamai.push_guard"


def _patch_git(local_sha: str | None, remote_sha: str | None,
               base_sha: str | None, local_ahead: int = 0,
               remote_ahead: int = 0):
    """Patch _run, local_head, remote_tip, merge_base, and divergence_info
    to simulate a git state without touching the filesystem."""

    def fake_run(repo, *args):
        if args[:2] == ("rev-list", "--count"):
            spec = args[2]
            if ".." in spec:
                # determine which direction
                left, right = spec.split("..")
                if left == (remote_sha or ""):
                    return 0, str(local_ahead)
                else:
                    return 0, str(remote_ahead)
            return 0, "0"
        if args[0] == "rev-parse":
            return 0, "fake"
        return 0, ""

    def fake_local_head(repo):
        return local_sha

    def fake_remote_tip(repo, remote="origin", branch="main"):
        return remote_sha

    def fake_merge_base(repo, left, right):
        return base_sha

    return [
        patch(f"{MODULE}._run", side_effect=fake_run),
        patch(f"{MODULE}.local_head", side_effect=fake_local_head),
        patch(f"{MODULE}.remote_tip", side_effect=fake_remote_tip),
        patch(f"{MODULE}.merge_base", side_effect=fake_merge_base),
    ]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

class TestDivergenceSummary:

    def test_no_commits(self):
        """Repo with no commits returns 'no commits'."""
        from iamai.push_guard import divergence_summary
        patches = _patch_git(None, None, None)
        for p in patches:
            p.start()
        try:
            result = divergence_summary(Path("/fake"))
            assert result == "no commits"
        finally:
            for p in patches:
                p.stop()

    def test_no_remote(self):
        """Local has commits but no tracking ref → 'no remote'."""
        from iamai.push_guard import divergence_summary
        patches = _patch_git("aaa111", None, None)
        for p in patches:
            p.start()
        try:
            result = divergence_summary(Path("/fake"))
            assert result == "no remote"
        finally:
            for p in patches:
                p.stop()

    def test_clean(self):
        """Local and remote at same SHA → 'clean'."""
        from iamai.push_guard import divergence_summary
        patches = _patch_git("aaa111", "aaa111", "aaa111", 0, 0)
        for p in patches:
            p.start()
        try:
            result = divergence_summary(Path("/fake"))
            assert result == "clean"
        finally:
            for p in patches:
                p.stop()

    def test_ahead(self):
        """Local ahead by 3 commits, remote unchanged → 'ahead 3'."""
        from iamai.push_guard import divergence_summary
        patches = _patch_git("bbb222", "aaa111", "aaa111", 3, 0)
        for p in patches:
            p.start()
        try:
            result = divergence_summary(Path("/fake"))
            assert result == "ahead 3"
        finally:
            for p in patches:
                p.stop()

    def test_behind(self):
        """Remote ahead by 2 commits, local unchanged → 'behind 2'."""
        from iamai.push_guard import divergence_summary
        patches = _patch_git("aaa111", "ccc333", "aaa111", 0, 2)
        for p in patches:
            p.start()
        try:
            result = divergence_summary(Path("/fake"))
            assert result == "behind 2"
        finally:
            for p in patches:
                p.stop()

    def test_diverged(self):
        """Both sides moved → 'diverged (1 local, 2 remote)'."""
        from iamai.push_guard import divergence_summary
        patches = _patch_git("bbb222", "ccc333", "aaa111", 1, 2)
        for p in patches:
            p.start()
        try:
            result = divergence_summary(Path("/fake"))
            assert result == "diverged (1 local, 2 remote)"
        finally:
            for p in patches:
                p.stop()
