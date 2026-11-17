"""tests for tools/push_recover.sh — validate the recovery script logic.

These tests exercise the script's behavior in controlled git repos
(temporary directories) rather than mocking subprocess calls. Each test
creates an ephemeral repo, sets up a conflict scenario, and verifies
the script's exit code and side effects.

written by Qwen, caretaker visit 670, 2026-11-17.
"""

import os
import subprocess
import tempfile
import textwrap

import pytest


SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "tools", "push_recover.sh"
)


def _run(cmd, cwd=None, check=True, env=None):
    """Run a shell command, return CompletedProcess."""
    merged = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.io",
              "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.io"}
    if env:
        merged.update(env)
    return subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True,
        check=check, env=merged,
    )


@pytest.fixture
def repo_pair(tmp_path):
    """Create a bare 'remote' repo and a clone with an initial commit."""
    bare = tmp_path / "remote.git"
    clone = tmp_path / "clone"

    _run(f"git init --bare {bare}")
    _run(f"git clone {bare} {clone}")
    # initial commit so main branch exists
    (clone / "README.md").write_text("# test\n")
    _run("git add -A && git commit -m 'init'", cwd=clone)
    _run("git branch -M main", cwd=clone)
    _run("git push origin main", cwd=clone)
    return bare, clone


def _make_other_clone(bare, other_path):
    """Create a second clone that tracks origin/main properly."""
    _run(f"git clone {bare} {other_path}")
    # ensure local branch is named main and tracks origin/main
    _run("git checkout main", cwd=other_path, check=False)
    _run("git branch -M main", cwd=other_path)


class TestPushRecoverHappyPath:
    """No divergence → push succeeds immediately."""

    def test_clean_push_succeeds(self, repo_pair):
        _, clone = repo_pair
        (clone / "a.txt").write_text("hello")
        _run("git add -A && git commit -m 'add a'", cwd=clone)
        result = _run(f"bash {SCRIPT} origin main", cwd=clone)
        assert result.returncode == 0
        assert "push succeeded" in result.stdout

    def test_dirty_tree_is_stashed_and_restored(self, repo_pair):
        _, clone = repo_pair
        # commit something pushable
        (clone / "b.txt").write_text("committed")
        _run("git add -A && git commit -m 'add b'", cwd=clone)
        # leave a dirty file
        (clone / "c.txt").write_text("uncommitted")
        result = _run(f"bash {SCRIPT} origin main", cwd=clone)
        assert result.returncode == 0
        # dirty file should still be present (stash pop restored it)
        assert (clone / "c.txt").read_text() == "uncommitted"


class TestPushRecoverDivergence:
    """Remote has diverged → script must rebase then push."""

    def test_rebase_resolves_cleanly(self, repo_pair):
        bare, clone = repo_pair

        # simulate another agent pushing to remote
        other = clone.parent / "other_clone"
        _make_other_clone(bare, other)
        (other / "d.txt").write_text("from other")
        _run("git add -A && git commit -m 'other push'", cwd=other)
        _run("git push origin main", cwd=other)

        # local clone now has diverged
        (clone / "e.txt").write_text("from clone")
        _run("git add -A && git commit -m 'local push'", cwd=clone)

        result = _run(f"bash {SCRIPT} origin main", cwd=clone)
        assert result.returncode == 0
        # both files should exist after rebase
        assert (clone / "d.txt").exists()
        assert (clone / "e.txt").exists()

    def test_dirty_tree_with_divergence(self, repo_pair):
        bare, clone = repo_pair

        # remote divergence
        other = clone.parent / "other2"
        _make_other_clone(bare, other)
        (other / "f.txt").write_text("other content")
        _run("git add -A && git commit -m 'other diverge'", cwd=other)
        _run("git push origin main", cwd=other)

        # local commit + dirty tree
        (clone / "g.txt").write_text("local commit")
        _run("git add -A && git commit -m 'local commit'", cwd=clone)
        (clone / "h.txt").write_text("dirty")

        result = _run(f"bash {SCRIPT} origin main", cwd=clone)
        assert result.returncode == 0
        assert (clone / "h.txt").read_text() == "dirty"


class TestPushRecoverEdgeCases:
    """Edge cases: empty stash, no-op push, not-a-repo."""

    def test_not_a_git_repo(self, tmp_path):
        result = _run(
            f"bash {SCRIPT} origin main",
            cwd=tmp_path, check=False,
        )
        assert result.returncode == 2
        assert "not inside a git repository" in result.stderr

    def test_no_commits_to_push(self, repo_pair):
        _, clone = repo_pair
        # nothing new committed; push should still succeed (no-op)
        result = _run(f"bash {SCRIPT} origin main", cwd=clone)
        assert result.returncode == 0

    def test_custom_remote_branch(self, repo_pair):
        _, clone = repo_pair
        _run("git checkout -b feature && git push origin feature", cwd=clone)
        (clone / "feat.txt").write_text("feature work")
        _run("git add -A && git commit -m 'feat'", cwd=clone)
        result = _run(f"bash {SCRIPT} origin feature", cwd=clone)
        assert result.returncode == 0


class TestScriptStructure:
    """Verify the script file itself is well-formed."""

    def test_script_exists_and_executable_syntax(self):
        assert os.path.isfile(SCRIPT), f"script not found at {SCRIPT}"
        result = _run(f"bash -n {SCRIPT}")
        assert result.returncode == 0, f"syntax error: {result.stderr}"

    def test_script_has_shebang(self):
        with open(SCRIPT) as f:
            first_line = f.readline().strip()
        assert first_line.startswith("#!/"), "missing shebang"

    def test_script_has_documentation(self):
        content = open(SCRIPT).read()
        assert "Usage:" in content or "usage:" in content
        assert "Exit codes:" in content or "exit code" in content.lower()

    def test_exit_codes_documented(self):
        content = open(SCRIPT).read()
        for code in ["0", "1", "2", "3"]:
            assert code in content, f"exit code {code} not documented"
