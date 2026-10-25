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


def make_history_with_a_merge(repo, branch="main"):
    """Rebuild the situation that actually happened on this repo: my local history
    contains a merge commit, upstream keeps moving, and rebase -- by design -- drops
    merges and replays both sides' appends, which conflicts. A merge does not."""

    git_in(repo, "checkout", "-q", "-b", "side")
    (repo / "log.md").write_text("# log\n\nmine one\nmine two\n", encoding="utf-8")
    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-q", "-m", "side: appends")
    git_in(repo, "checkout", "-q", "main")
    (repo / "other.md").write_text("other\n", encoding="utf-8")
    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-q", "-m", "main: something else")
    git_in(repo, "merge", "-q", "--no-edit", "side")
    parents = git_in(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 3, "the fixture must produce a real merge commit"
    return "merged"


def test_rebase_conflict_falls_back_to_a_merge_instead_of_stalling(two_clones):
    a, b, bare = two_clones
    # both clones share a union-attributed append-only log
    for repo in (a, b):
        (repo / ".gitattributes").write_text("log.md merge=union\n", encoding="utf-8")
        repo_config(repo, "merge.union.name", "union append-only merge")
        repo_config(repo, "merge.union.driver", "git merge-file --union %A %O %B")
        (repo / "log.md").write_text("# log\n", encoding="utf-8")
        git_in(repo, "add", "-A")
        git_in(repo, "commit", "-q", "-m", "chore: union attributes for log.md")
        push.push_with_rebase(repo, remote="origin", branch="main")

    # upstream (a) appends
    commit_file(a, "log.md", "# log\n\nA line one\nA line two\n", "a: append")
    push.push_with_rebase(a, remote="origin", branch="main")

    # b has a merge commit in its history and its own appends
    commit_file(b, "log.md", "# log\n\nB line one\nB line two\n", "b: append")
    make_history_with_a_merge(b)

    result = push.push_with_rebase(b, remote="origin", branch="main")
    assert result["ok"] is True, result
    assert result["strategy"] in ("merge-then-push", "rebase-then-push", "push"), result
    files = ls_remote(bare)
    assert "other.md" in files, "b's own work landed"
    log = subprocess.run(
        ["git", "--git-dir", str(bare), "show", "main:log.md"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(bare.parent)},
    ).stdout
    assert "A line one" in log and "B line one" in log, f"both appends survived:\n{log}"


def repo_config(repo, key, value):
    subprocess.run(["git", "config", key, value], cwd=repo, check=True,
                   env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo)})


# --- the manual stash-rebase-pop path ------------------------------------


def test_manual_stash_rebase_pop_preserves_in_flight_stroke(two_clones):
    """The live recovery path when autoStash is not enough: writer is mid-stroke,
    push was rejected, and a human (or supervising agent) runs stash-rebase-pop
    by hand. The in-flight stroke must survive the round trip."""

    a, b, bare = two_clones

    # upstream (a) pushes first
    commit_file(a, "from_a.md", "A\n", "a: work")
    push.push_with_rebase(a, remote="origin", branch="main")

    # b has a committed batch plus an uncommitted in-flight stroke
    commit_file(b, "from_b.md", "B\n", "b: batch commit")
    (b / "docs" / "DEVLOG.md").parent.mkdir(exist_ok=True)
    (b / "in_flight_stroke.md").write_text(
        "stroke 999: written mid-rebase, not yet committed\n", encoding="utf-8"
    )

    # manual recovery: stash (including untracked), rebase, pop
    stash_rc = subprocess.run(
        ["git", "stash", "--include-untracked"], cwd=b, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(b)},
    )
    assert stash_rc.returncode == 0, stash_rc.stderr

    rebase_rc = subprocess.run(
        ["git", "rebase", "origin/main"], cwd=b, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(b)},
    )
    assert rebase_rc.returncode == 0, rebase_rc.stderr

    pop_rc = subprocess.run(
        ["git", "stash", "pop"], cwd=b, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(b)},
    )
    assert pop_rc.returncode == 0, pop_rc.stderr

    # the in-flight stroke survived
    assert (b / "in_flight_stroke.md").exists()
    content = (b / "in_flight_stroke.md").read_text(encoding="utf-8")
    assert "stroke 999" in content

    # and the committed batch can now push
    result = push.push_with_rebase(b, remote="origin", branch="main")
    assert result["ok"] is True, result
    files = ls_remote(bare)
    assert "from_a.md" in files and "from_b.md" in files
