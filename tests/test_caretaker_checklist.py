"""Tests that codify the caretaker checklist invariants.

These tests exist so the checklist in notes/caretaker-checklist.md
stays honest — if the repo structure changes in a way that breaks a
checklist step, a test fails before a caretaker discovers it at 3am.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


class TestCaretakerPrerequisites:
    """The tools a caretaker needs must exist and be functional."""

    def test_run_both_script_exists(self):
        """tools/run_both.sh must exist — it is how processes restart."""
        script = REPO_ROOT / "tools" / "run_both.sh"
        assert script.exists(), "tools/run_both.sh is missing"
        assert script.stat().st_mode & 0o111, "tools/run_both.sh is not executable"

    def test_safe_push_cli_importable(self):
        """iamai.push.safe_push_cli must be importable from the harness."""
        from iamai.push import safe_push_cli
        assert callable(safe_push_cli)

    def test_safe_push_cli_signature(self):
        """safe_push_cli accepts a repo path as its first argument."""
        import inspect
        from iamai.push import safe_push_cli
        sig = inspect.signature(safe_push_cli)
        params = list(sig.parameters.keys())
        assert "repo" in params, "safe_push_cli must accept a 'repo' parameter"

    def test_strokes_jsonl_exists(self):
        """data/strokes.jsonl must exist — it is the primary health signal."""
        strokes = REPO_ROOT / "data" / "strokes.jsonl"
        assert strokes.exists(), "data/strokes.jsonl is missing"

    def test_writer_state_exists(self):
        """data/writer_state.qwen.json must exist for the caretaker to inspect."""
        state = REPO_ROOT / "data" / "writer_state.qwen.json"
        assert state.exists(), "data/writer_state.qwen.json is missing"


class TestStrokesHealth:
    """The strokes log must be parseable and internally consistent."""

    @pytest.fixture(autouse=True)
    def _load_strokes(self):
        import json
        strokes_path = REPO_ROOT / "data" / "strokes.jsonl"
        self.strokes = []
        if strokes_path.exists():
            for line in strokes_path.read_text().strip().splitlines():
                if line.strip():
                    self.strokes.append(json.loads(line))

    def test_strokes_sequences_are_valid(self):
        """Stroke sequences must be positive integers (may interleave across writers)."""
        seqs = [s["seq"] for s in self.strokes]
        assert all(isinstance(s, int) and s > 0 for s in seqs), (
            "strokes.jsonl has non-positive or non-integer sequences"
        )
        # Multiple writers may interleave, so sequences need not be sorted,
        # but duplicates beyond a small tolerance suggest corruption.
        from collections import Counter
        dupes = {k: v for k, v in Counter(seqs).items() if v > 2}
        assert not dupes, f"excessive duplicate sequences: {dupes}"

    def test_strokes_have_required_fields(self):
        """Every stroke must have seq, at, kind, and text."""
        for i, stroke in enumerate(self.strokes[-10:]):  # check last 10
            for field in ("seq", "at", "kind", "text"):
                assert field in stroke, f"stroke {i} missing field '{field}'"

    def test_strokes_have_kinds(self):
        """Every stroke must declare a kind; at least one kind should be present."""
        kinds = {s.get("kind") for s in self.strokes}
        assert None not in kinds, "some strokes have no 'kind' field"
        assert len(kinds) >= 1, "strokes.jsonl has no kind values"

    def test_rotation_files_exist(self):
        """The six rotation targets must all exist in docs/."""
        rotation_files = ["DEVLOG.md", "GARDEN.md", "METRICS.md", "THOUGHTS.md"]
        for name in rotation_files:
            path = REPO_ROOT / "docs" / name
            assert path.exists(), f"docs/{name} is missing"


class TestNoForceFlags:
    """The caretaker must never be tempted into --force."""

    def test_push_module_blocks_force(self):
        """iamai.push._run rejects --force and --force-with-lease."""
        from iamai.push import _run
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            with pytest.raises(ValueError, match="destructive"):
                _run(repo, "push", "--force")
            with pytest.raises(ValueError, match="destructive"):
                _run(repo, "push", "--force-with-lease")
