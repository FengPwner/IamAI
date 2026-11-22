"""Tests for iamai.push_conflict_anatomy.

push_conflict_anatomy classifies git push rejection output into
structured types and recommends resolution strategies. These tests
cover classification, file extraction, resolution plans, and edge
cases.
"""

import pytest

from iamai.push_conflict_anatomy import (
    PushRejection,
    classify_push_failure,
    recommend_resolution,
    diagnose_push,
    _extract_conflicting_files,
    _extract_remote_branch,
    _first_meaningful_line,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NON_FAST_FORWARD_STDERR = """\
To github.com:FengPwner/IamAI.git
 ! [rejected]        main -> main (fetch first)
error: failed to push some refs to 'github.com:FengPwner/IamAI.git'
hint: Updates were rejected because the remote contains work that you do not
hint: have locally. This is usually caused by another repository pushing to
hint: the same ref. If you want to integrate the remote changes, use
hint: 'git pull' before pushing again.
hint: See the 'Note about fast-forwards' in 'git push --help' for details.
"""

PERMISSION_DENIED_STDERR = """\
ERROR: Permission to FengPwner/IamAI.git denied to deploy key.
fatal: Could not read from remote repository.
Please make sure you have the correct access rights.
"""

BRANCH_PROTECTED_STDERR = """\
remote: error: GH006: Protected branch update failed for refs/heads/main
remote: - Required status check "ci" must pass before merging.
To github.com:FengPwner/IamAI.git
 ! [remote rejected] main -> main (protected branch hook declined)
error: failed to push some refs to 'github.com:FengPwner/IamAI.git'
"""

HOOK_DECLINED_STDERR = """\
remote: error: pre-receive hook declined
remote: Your push was rejected because the commit message is too long.
To github.com:FengPwner/IamAI.git
 ! [remote rejected] main -> main (pre-receive hook declined)
error: failed to push some refs to 'github.com:FengPwner/IamAI.git'
"""

MERGE_COMMIT_STDERR = """\
remote: error: refusing to merge commit because it contains merge commits
remote: Please rebase your branch and try again.
To github.com:FengPwner/IamAI.git
 ! [remote rejected] main -> main (merge commit not allowed)
error: failed to push some refs to 'github.com:FengPwner/IamAI.git'
"""


# ---------------------------------------------------------------------------
# PushRejection dataclass
# ---------------------------------------------------------------------------


class TestPushRejection:
    def test_default_fields(self):
        r = PushRejection(type="non_fast_forward")
        assert r.type == "non_fast_forward"
        assert r.message == ""
        assert r.files == []
        assert r.remote_branch is None
        assert r.raw_stderr == ""

    def test_is_resolvable_nff(self):
        r = PushRejection(type="non_fast_forward")
        assert r.is_resolvable() is True

    def test_is_resolvable_reject_merge(self):
        r = PushRejection(type="reject_merge_commit")
        assert r.is_resolvable() is True

    def test_is_resolvable_permission(self):
        r = PushRejection(type="permission_denied")
        assert r.is_resolvable() is False

    def test_is_resolvable_branch_protected(self):
        r = PushRejection(type="branch_protected")
        assert r.is_resolvable() is False

    def test_is_resolvable_hook_declined(self):
        r = PushRejection(type="hook_declined")
        assert r.is_resolvable() is False

    def test_requires_human_permission(self):
        r = PushRejection(type="permission_denied")
        assert r.requires_human() is True

    def test_requires_human_protected(self):
        r = PushRejection(type="branch_protected")
        assert r.requires_human() is True

    def test_requires_human_nff(self):
        r = PushRejection(type="non_fast_forward")
        assert r.requires_human() is False

    def test_requires_human_unknown(self):
        r = PushRejection(type="unknown")
        assert r.requires_human() is False

    def test_files_populated(self):
        r = PushRejection(type="non_fast_forward", files=["a.py", "b.py"])
        assert len(r.files) == 2
        assert "a.py" in r.files

    def test_remote_branch_populated(self):
        r = PushRejection(type="non_fast_forward", remote_branch="main")
        assert r.remote_branch == "main"


# ---------------------------------------------------------------------------
# classify_push_failure
# ---------------------------------------------------------------------------


class TestClassify:
    def test_non_fast_forward(self):
        r = classify_push_failure(NON_FAST_FORWARD_STDERR)
        assert r.type == "non_fast_forward"
        assert r.message  # non-empty first meaningful line

    def test_permission_denied(self):
        r = classify_push_failure(PERMISSION_DENIED_STDERR)
        assert r.type == "permission_denied"

    def test_branch_protected(self):
        r = classify_push_failure(BRANCH_PROTECTED_STDERR)
        assert r.type == "branch_protected"

    def test_hook_declined(self):
        r = classify_push_failure(HOOK_DECLINED_STDERR)
        assert r.type == "hook_declined"

    def test_merge_commit(self):
        r = classify_push_failure(MERGE_COMMIT_STDERR)
        assert r.type == "reject_merge_commit"

    def test_empty_string(self):
        r = classify_push_failure("")
        assert r.type == "unknown"
        assert r.raw_stderr == ""

    def test_garbage_input(self):
        r = classify_push_failure("totally unrelated output\nfoo bar baz")
        assert r.type == "unknown"
        assert r.raw_stderr != ""

    def test_remote_branch_extracted(self):
        r = classify_push_failure(NON_FAST_FORWARD_STDERR)
        assert r.remote_branch == "main"

    def test_message_not_hint(self):
        r = classify_push_failure(NON_FAST_FORWARD_STDERR)
        assert not r.message.startswith("hint:")

    def test_raw_stderr_preserved(self):
        r = classify_push_failure(NON_FAST_FORWARD_STDERR)
        assert r.raw_stderr == NON_FAST_FORWARD_STDERR

    def test_case_insensitive(self):
        r = classify_push_failure("ERROR: PERMISSION DENIED")
        assert r.type == "permission_denied"

    def test_partial_match(self):
        r = classify_push_failure("non-fast-forward update")
        assert r.type == "non_fast_forward"


# ---------------------------------------------------------------------------
# recommend_resolution
# ---------------------------------------------------------------------------


class TestRecommend:
    def test_nff_strategy(self):
        rej = PushRejection(type="non_fast_forward")
        rec = recommend_resolution(rej)
        assert rec["strategy"] == "rebase"
        assert rec["risk"] == "low"
        assert rec["auto_safe"] is True

    def test_nff_steps_contain_pull_rebase(self):
        rej = PushRejection(type="non_fast_forward")
        rec = recommend_resolution(rej)
        assert any("pull --rebase" in s for s in rec["steps"])

    def test_nff_branch_substitution(self):
        rej = PushRejection(type="non_fast_forward")
        rec = recommend_resolution(rej, branch="develop")
        assert any("develop" in s for s in rec["steps"])

    def test_permission_strategy(self):
        rej = PushRejection(type="permission_denied")
        rec = recommend_resolution(rej)
        assert rec["strategy"] == "credential_refresh"
        assert rec["auto_safe"] is False

    def test_protected_branch_strategy(self):
        rej = PushRejection(type="branch_protected")
        rec = recommend_resolution(rej)
        assert rec["strategy"] == "branch_policy"
        assert rec["auto_safe"] is True

    def test_protected_branch_creates_branch(self):
        rej = PushRejection(type="branch_protected")
        rec = recommend_resolution(rej)
        assert any("checkout -b" in s for s in rec["steps"])

    def test_hook_strategy(self):
        rej = PushRejection(type="hook_declined")
        rec = recommend_resolution(rej)
        assert rec["strategy"] == "investigate"
        assert rec["auto_safe"] is False

    def test_merge_commit_strategy(self):
        rej = PushRejection(type="reject_merge_commit")
        rec = recommend_resolution(rej)
        assert rec["strategy"] == "rebase"
        assert rec["auto_safe"] is False

    def test_unknown_strategy(self):
        rej = PushRejection(type="unknown")
        rec = recommend_resolution(rej)
        assert rec["strategy"] == "manual"
        assert rec["risk"] == "unknown"

    def test_all_steps_are_strings(self):
        rej = PushRejection(type="non_fast_forward")
        rec = recommend_resolution(rej)
        for step in rec["steps"]:
            assert isinstance(step, str)

    def test_default_branch_main(self):
        rej = PushRejection(type="non_fast_forward")
        rec = recommend_resolution(rej)
        assert any("main" in s for s in rec["steps"])


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestExtractConflictingFiles:
    def test_no_files(self):
        assert _extract_conflicting_files(NON_FAST_FORWARD_STDERR) == []

    def test_with_conflict_lines(self):
        stderr = "CONFLICT (content): docs/README.md\nerror: merge conflict in src/main.py"
        files = _extract_conflicting_files(stderr)
        assert "docs/README.md" in files
        assert "src/main.py" in files

    def test_dedup(self):
        stderr = "CONFLICT: a.py\nerror: a.py\nCONFLICT: b.py"
        files = _extract_conflicting_files(stderr)
        assert len(files) == 2

    def test_empty(self):
        assert _extract_conflicting_files("") == []


class TestExtractRemoteBranch:
    def test_standard_format(self):
        stderr = " ! [rejected]        main -> main (fetch first)"
        assert _extract_remote_branch(stderr) == "main"

    def test_develop_branch(self):
        stderr = " ! [rejected]        develop -> develop (non-fast-forward)"
        assert _extract_remote_branch(stderr) == "develop"

    def test_no_match(self):
        assert _extract_remote_branch("nothing here") is None

    def test_empty(self):
        assert _extract_remote_branch("") is None


class TestFirstMeaningfulLine:
    def test_skips_hints(self):
        stderr = "hint: do this\nhint: and this\nactual error message"
        assert _first_meaningful_line(stderr) == "actual error message"

    def test_skips_empty_lines(self):
        stderr = "\n\n  \nfirst real line\nsecond"
        assert _first_meaningful_line(stderr) == "first real line"

    def test_all_hints(self):
        stderr = "hint: one\nhint: two"
        assert _first_meaningful_line(stderr) == ""

    def test_empty_input(self):
        assert _first_meaningful_line("") == ""

    def test_first_line_is_meaningful(self):
        stderr = "error: something broke\nhint: try this"
        assert _first_meaningful_line(stderr) == "error: something broke"


# ---------------------------------------------------------------------------
# diagnose_push (convenience)
# ---------------------------------------------------------------------------


class TestDiagnosePush:
    def test_returns_both_keys(self):
        result = diagnose_push(NON_FAST_FORWARD_STDERR)
        assert "rejection" in result
        assert "resolution" in result

    def test_rejection_is_push_rejection(self):
        result = diagnose_push(NON_FAST_FORWARD_STDERR)
        assert isinstance(result["rejection"], PushRejection)

    def test_resolution_is_dict(self):
        result = diagnose_push(NON_FAST_FORWARD_STDERR)
        assert isinstance(result["resolution"], dict)

    def test_types_match(self):
        result = diagnose_push(NON_FAST_FORWARD_STDERR)
        assert result["rejection"].type == "non_fast_forward"
        assert result["resolution"]["strategy"] == "rebase"

    def test_empty_input(self):
        result = diagnose_push("")
        assert result["rejection"].type == "unknown"
        assert result["resolution"]["strategy"] == "manual"

    def test_custom_branch(self):
        result = diagnose_push(PERMISSION_DENIED_STDERR, branch="release/1.0")
        assert any("release/1.0" in s for s in result["resolution"]["steps"])
