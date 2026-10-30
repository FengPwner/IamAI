"""Tests for tools/push_rejection_classifier.py.

Covers the five rejection categories plus the OK (success) case,
edge cases with mixed-case stderr, and the recovery-steps helper.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tools.push_rejection_classifier import (
    classify_push_stderr,
    push_recovery_steps,
)

# ---------- classification tests ----------


def test_ok_on_empty_stderr():
    assert classify_push_stderr("")["kind"] == "OK"


def test_ok_on_whitespace_only():
    assert classify_push_stderr("   \n  ")["kind"] == "OK"


def test_fetch_first_real_message():
    stderr = (
        "To github.com:FengPwner/IamAI.git\n"
        " ! [rejected]        main -> main (fetch first)\n"
        "error: failed to push some refs to 'github.com:FengPwner/IamAI.git'\n"
        "hint: Updates were rejected because the remote contains work that you do not\n"
        "hint: have locally."
    )
    result = classify_push_stderr(stderr)
    assert result["kind"] == "FETCH_FIRST"
    assert result["severity"] == "medium"


def test_fetch_first_case_insensitive():
    stderr = "REJECTED main -> main (FETCH FIRST)"
    result = classify_push_stderr(stderr)
    assert result["kind"] == "FETCH_FIRST"


def test_permission_denied_publickey():
    stderr = "git@github.com: Permission denied (publickey).\r\nfatal: Could not read from remote repository."
    result = classify_push_stderr(stderr)
    assert result["kind"] == "PERMISSION"
    assert result["severity"] == "high"


def test_permission_denied_auth_failed():
    stderr = "remote: Authentication failed"
    result = classify_push_stderr(stderr)
    assert result["kind"] == "PERMISSION"


def test_network_dns_failure():
    stderr = "ssh: Could not resolve hostname github.com: Name or service not known"
    result = classify_push_stderr(stderr)
    assert result["kind"] == "NETWORK"
    assert result["severity"] == "low"


def test_network_connection_refused():
    stderr = "ssh: connect to host github.com port 22: Connection refused"
    result = classify_push_stderr(stderr)
    assert result["kind"] == "NETWORK"


def test_hook_rejected_pre_receive():
    stderr = "remote: error: pre-receive hook declined\nTo github.com:owner/repo.git\n ! [remote rejected] main -> main"
    result = classify_push_stderr(stderr)
    assert result["kind"] == "HOOK_REJECTED"
    assert result["severity"] == "high"


def test_non_fast_forward():
    stderr = "error: failed to push some refs\nhint: Updates were rejected because the tip of your current branch is behind\nnon-fast-forward"
    result = classify_push_stderr(stderr)
    assert result["kind"] in ("NON_FAST_FORWARD", "FETCH_FIRST")


def test_unknown_stderr():
    stderr = "something completely unexpected happened here"
    result = classify_push_stderr(stderr)
    assert result["kind"] == "UNKNOWN"


def test_rejected_alone_maps_to_fetch_first():
    result = classify_push_stderr("the push was rejected by server")
    assert result["kind"] == "FETCH_FIRST"


def test_denied_alone_maps_to_permission():
    result = classify_push_stderr("access was denied for this operation")
    assert result["kind"] == "PERMISSION"


# ---------- recovery steps tests ----------


def test_fetch_first_has_stash_pull_pop_push():
    steps = push_recovery_steps({"kind": "FETCH_FIRST"})
    assert len(steps) == 4
    assert "stash" in steps[0]
    assert "rebase" in steps[1]
    assert "pop" in steps[2]
    assert "push" in steps[3]


def test_permission_rescues_ssh_key():
    steps = push_recovery_steps({"kind": "PERMISSION"})
    assert any("ssh_push_rescue" in s for s in steps)


def test_network_checks_connectivity():
    steps = push_recovery_steps({"kind": "NETWORK"})
    assert any("ping" in s or "curl" in s for s in steps)


def test_unknown_kind_returns_inspect_steps():
    steps = push_recovery_steps({"kind": "UNKNOWN"})
    assert len(steps) >= 1
    assert any("inspect" in s or "status" in s for s in steps)


def test_all_fix_fields_non_empty():
    """Every classification should have a non-empty fix string."""
    test_cases = [
        "rejected main (fetch first)",
        "Permission denied (publickey)",
        "Could not resolve host",
        "pre-receive hook declined",
        "non-fast-forward updates were rejected",
        "",
    ]
    for stderr in test_cases:
        result = classify_push_stderr(stderr)
        assert result["fix"], f"Empty fix for stderr: {stderr!r}"
        assert result["severity"] in ("none", "low", "medium", "high")
