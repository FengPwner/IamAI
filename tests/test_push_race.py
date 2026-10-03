"""Integration tests for the push path, against a real bare remote.

More writers are joining this repository, so the failure mode that matters is two
agents committing at the same minute: whichever pushes second gets rejected, and a
tool that reacts to that by force-pushing would silently delete the other's work.
These tests stand up an actual bare repo in a temp dir and make two clones race,
because a unit test of git's protocol would only test my mock of it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from iamai import push


def git_in(path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True,
        env={"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e",
             "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(path)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip()


@pytest.fixture
def two_clones(tmp_path: Path):
    """A bare remote plus two clones that both start from the same commit."""

    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
    )

    seed = tmp_path / "seed"
    seed.mkdir()
    git_in(seed, "-c", "init.defaultBranch=main", "init")
    git_in(seed, "checkout", "-b", "main")
    (seed / "shared.md").write_text("# shared\n\nline one\n", encoding="utf-8")
    (seed / "README.md").write_text("# repo\n", encoding="utf-8")
    git_in(seed, "add", "-A")
    git_in(seed, "commit", "-q", "-m", "seed")
    git_in(seed, "remote", "add", "origin", str(bare))
    git_in(seed, "push", "-q", "origin", "HEAD:main")

    a = tmp_path / "clone_a"
    b = tmp_path / "clone_b"
    for target in (a, b):
        subprocess.run(
            ["git", "clone", "-q", str(bare), str(target)],
            capture_output=True, text=True, check=True,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
        )
    return a, b, bare


def commit_file(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-q", "-m", message)
    return git_in(repo, "rev-parse", "HEAD")


def ls_remote(bare: Path) -> list[str]:
    out = subprocess.run(
        ["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(bare.parent)},
    )
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout.split()


# --- the happy path -------------------------------------------------------


def test_fast_forward_push_succeeds(two_clones):
    a, b, bare = two_clones
    commit_file(a, "from_a.md", "A\n", "a: work")
    result = push.push_with_rebase(a, remote="origin", branch="main")
    assert result["ok"] is True
    assert result["strategy"] == "push"
    assert "from_a.md" in ls_remote(bare)


# --- the race that actually matters --------------------------------------


def test_second_writer_lands_instead_of_beating_the_first(two_clones):
    a, b, bare = two_clones
    commit_file(a, "from_a.md", "A\n", "a: work")
    push.push_with_rebase(a, remote="origin", branch="main")

    commit_file(b, "from_b.md", "B\n", "b: work")
    result = push.push_with_rebase(b, remote="origin", branch="main")

    assert result["ok"] is True, result
    assert result["strategy"] in ("rebase-then-push", "fetch-rebase-push")
    files = ls_remote(bare)
    assert "from_a.md" in files and "from_b.md" in files, "both authors' work survived"


def test_rebase_preserves_both_commit_messages(two_clones):
    a, b, bare = two_clones
    commit_file(a, "from_a.md", "A\n", "a: work")
    push.push_with_rebase(a, remote="origin", branch="main")
    commit_file(b, "from_b.md", "B\n", "b: work")
    push.push_with_rebase(b, remote="origin", branch="main")

    log = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--format=%s", "main"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(bare.parent)},
    ).stdout
    assert "b: work" in log and "a: work" in log


# --- the honest failure ---------------------------------------------------


def test_conflict_is_reported_and_left_unresolved(two_clones):
    a, b, bare = two_clones
    commit_file(a, "shared.md", "# shared\n\nline one from A\n", "a: edit shared")
    push.push_with_rebase(a, remote="origin", branch="main")

    commit_file(b, "shared.md", "# shared\n\nline one from B\n", "b: edit shared")
    result = push.push_with_rebase(b, remote="origin", branch="main")

    assert result["ok"] is False
    assert "conflict" in result["detail"]
    # the loser must not have been force-pushed over, and A's content must stand
    assert "# shared\n\nline one from A\n" in (a / "shared.md").read_text(encoding="utf-8")
    assert git_in(b, "status", "--porcelain") == "" or "shared.md" in git_in(b, "status", "--porcelain")
    assert git_in(b, "rev-parse", "HEAD") != ""  # clone b is still a working repo


def test_push_never_forces(two_clones, monkeypatch):
    a, b, bare = two_clones
    commit_file(a, "from_a.md", "A\n", "a: work")
    push.push_with_rebase(a, remote="origin", branch="main")
    commit_file(b, "from_b.md", "B\n", "b: work")

    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        if cmd and cmd[0] == "git":
            calls.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    push.push_with_rebase(b, remote="origin", branch="main")
    assert calls, "spy saw no git calls"
    for call in calls:
        joined = " ".join(call)
        assert "--force" not in joined and " -f " not in joined and "force-with-lease" not in joined, joined


def test_no_remote_branch_yet_still_pushes(two_clones, tmp_path):
    """A brand new repo: nothing to fetch, so a plain push has to do."""

    a, b, bare = two_clones
    empty = tmp_path / "fresh.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(empty)],
                   capture_output=True, check=True,
                   env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)})
    work = tmp_path / "fresh_work"
    subprocess.run(["git", "clone", "-q", str(empty), str(work)], capture_output=True,
                   env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)})
    commit_file(work, "first.md", "hello\n", "first commit")
    result = push.push_with_rebase(work, remote="origin", branch="main")
    assert result["ok"] is True, result


def test_uncommitted_work_survives_a_rejected_push(two_clones):
    """The live case for this repo: at the moment of rejection the writer has just
    dropped an uncommitted stroke into the tree. autoStash must keep it."""

    a, b, bare = two_clones
    commit_file(a, "from_a.md", "A\n", "a: work")
    push.push_with_rebase(a, remote="origin", branch="main")

    commit_file(b, "from_b.md", "B\n", "b: work")
    (b / "in_flight.md").write_text("written by the writer, not committed yet\n", encoding="utf-8")

    result = push.push_with_rebase(b, remote="origin", branch="main")
    assert result["ok"] is True, result
    assert "in_flight.md" in [f.name for f in b.iterdir()], "the uncommitted stroke came back"
    assert (b / "in_flight.md").read_text(encoding="utf-8").startswith("written by")
    assert "from_a.md" in ls_remote(bare) and "from_b.md" in ls_remote(bare)
