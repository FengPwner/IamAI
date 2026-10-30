"""tests for tools/ssh_key_localize.py

covers:
  - filesystem chmod detection (_chmod_works)
  - key discovery across candidate directories (_find_keys)
  - permission classification (safe vs hostile)
  - key localisation (copy + chmod 0600)
  - git sshCommand configuration
  - dry-run mode
  - JSON output structure
  - edge cases (missing dirs, unreadable files, no keys)

18 tests total.
"""

import json
import os
import stat
import subprocess
import tempfile
import textwrap

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "ssh_key_localize.py")


# ── _chmod_works ────────────────────────────────────────────────────────


class TestChmodWorks:
    def test_tmpfs_returns_true(self):
        """systemd-tmpfs / /tmp should honour chmod."""
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import _chmod_works
                    print(_chmod_works('/tmp'))
                """),
            ],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "True"

    def test_nonexistent_dir_returns_false(self):
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import _chmod_works
                    print(_chmod_works('/nonexistent/path/xyz'))
                """),
            ],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "False"


# ── _find_keys ──────────────────────────────────────────────────────────


class TestFindKeys:
    def test_finds_keys_in_repo_ssh_dir(self):
        """should find keys under ../.ssh relative to repo."""
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys, json; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import _find_keys
                    keys = _find_keys()
                    print(json.dumps(len(keys)))
                """),
            ],
            capture_output=True, text=True,
        )
        count = int(result.stdout.strip())
        assert count >= 1, "expected at least one key in the workspace"

    def test_key_entry_has_required_fields(self):
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys, json; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import _find_keys
                    keys = _find_keys()
                    if keys:
                        print(json.dumps(sorted(keys[0].keys())))
                """),
            ],
            capture_output=True, text=True,
        )
        fields = json.loads(result.stdout.strip())
        for f in ["path", "mode", "mode_int", "fs_chmod_ok", "safe_mode"]:
            assert f in fields, f"missing field: {f}"

    def test_no_keys_in_empty_dir(self):
        """create a temp dir with no keys — should find nothing there."""
        with tempfile.TemporaryDirectory() as d:
            result = subprocess.run(
                [
                    "python3", "-c",
                    textwrap.dedent(f"""\
                        import sys, os, json; sys.path.insert(0, {REPO!r})
                        # override HOME so ~/.ssh resolves to our empty dir
                        os.environ['HOME'] = {d!r}
                        from tools.ssh_key_localize import _find_keys
                        # only check if HOME-based search finds nothing extra
                        keys = [k for k in _find_keys() if k['path'].startswith({d!r})]
                        print(len(keys))
                    """),
                ],
                capture_output=True, text=True,
            )
            assert result.stdout.strip() == "0"


# ── _localize_key ───────────────────────────────────────────────────────


class TestLocalizeKey:
    def test_copies_with_correct_permissions(self):
        with tempfile.TemporaryDirectory() as src_dir:
            key = os.path.join(src_dir, "id_ed25519")
            with open(key, "w") as f:
                f.write("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n")
            os.chmod(key, 0o777)  # simulate FUSE

            result = subprocess.run(
                [
                    "python3", "-c",
                    textwrap.dedent(f"""\
                        import sys, json; sys.path.insert(0, {REPO!r})
                        from tools.ssh_key_localize import _localize_key
                        dest = _localize_key({key!r})
                        import os
                        print(json.dumps({{
                            "dest": dest,
                            "exists": os.path.exists(dest),
                            "mode": oct(os.stat(dest).st_mode & 0o777),
                        }}))
                    """),
                ],
                capture_output=True, text=True,
            )
            info = json.loads(result.stdout.strip())
            assert info["exists"]
            assert info["mode"] == "0o600"

    def test_dest_file_content_matches_source(self):
        with tempfile.TemporaryDirectory() as src_dir:
            key = os.path.join(src_dir, "test_key")
            content = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc123\n-----END OPENSSH PRIVATE KEY-----\n"
            with open(key, "w") as f:
                f.write(content)

            result = subprocess.run(
                [
                    "python3", "-c",
                    textwrap.dedent(f"""\
                        import sys; sys.path.insert(0, {REPO!r})
                        from tools.ssh_key_localize import _localize_key
                        dest = _localize_key({key!r})
                        with open(dest) as f:
                            sys.stdout.write(f.read())
                    """),
                ],
                capture_output=True, text=True,
            )
            assert result.stdout == content

    def test_dry_run_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as src_dir:
            key = os.path.join(src_dir, "id_rsa")
            with open(key, "w") as f:
                f.write("-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n")

            result = subprocess.run(
                [
                    "python3", "-c",
                    textwrap.dedent(f"""\
                        import sys, os; sys.path.insert(0, {REPO!r})
                        import tools.ssh_key_localize as m
                        m.DRY_RUN = True
                        dest = m._localize_key({key!r})
                        print(dest)
                        print(os.path.exists(dest))
                    """),
                ],
                capture_output=True, text=True,
            )
            lines = result.stdout.strip().split("\n")
            assert lines[1] == "False"  # file should NOT exist


# ── _git_ssh_command ────────────────────────────────────────────────────


class TestGitSshCommand:
    def test_includes_key_path(self):
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import _git_ssh_command
                    print(_git_ssh_command('/tmp/mykey'))
                """),
            ],
            capture_output=True, text=True,
        )
        cmd = result.stdout.strip()
        assert "-i /tmp/mykey" in cmd
        assert "StrictHostKeyChecking=no" in cmd
        assert "BatchMode=yes" in cmd

    def test_no_interactive_prompts(self):
        """BatchMode=yes prevents ssh-askpass popups."""
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import _git_ssh_command
                    print(_git_ssh_command('/x'))
                """),
            ],
            capture_output=True, text=True,
        )
        assert "BatchMode=yes" in result.stdout


# ── full run() ──────────────────────────────────────────────────────────


class TestRun:
    def test_returns_dict(self):
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys, json; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import run
                    report = run()
                    assert isinstance(report, dict)
                    print(json.dumps(sorted(report.keys())))
                """),
            ],
            capture_output=True, text=True,
        )
        fields = json.loads(result.stdout.strip())
        for f in ["action", "keys", "keys_found", "localised_path"]:
            assert f in fields

    def test_keys_found_is_nonzero(self):
        """our live repo should have at least one key."""
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import run
                    print(run()['keys_found'])
                """),
            ],
            capture_output=True, text=True,
        )
        assert int(result.stdout.strip()) >= 1

    def test_action_is_none_or_localised(self):
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import run
                    print(run()['action'])
                """),
            ],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() in ("none", "localised")


# ── CLI ─────────────────────────────────────────────────────────────────


class TestCLI:
    def test_json_output_is_valid(self):
        result = subprocess.run(
            ["python3", TOOL, "--json"],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        assert "keys_found" in data

    def test_dry_run_json(self):
        result = subprocess.run(
            ["python3", TOOL, "--json", "--dry-run"],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        assert isinstance(data["keys"], list)

    def test_plain_output_not_empty(self):
        result = subprocess.run(
            ["python3", TOOL],
            capture_output=True, text=True,
        )
        assert len(result.stdout.strip()) > 0

    def test_configure_git_flag(self):
        result = subprocess.run(
            ["python3", TOOL, "--json", "--configure-git"],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        # should have ssh_command in output when git is configured
        if data.get("git_configured"):
            assert "ssh_command" in data


# ── integration: end-to-end localise + ssh test ─────────────────────────


class TestIntegration:
    def test_localise_then_ssh_test(self):
        """localise the key, then verify SSH accepts it."""
        result = subprocess.run(
            [
                "python3", "-c",
                textwrap.dedent(f"""\
                    import sys, os, subprocess; sys.path.insert(0, {REPO!r})
                    from tools.ssh_key_localize import run
                    report = run()
                    key = report.get('localised_path')
                    if not key or not os.path.exists(key):
                        print('SKIP: no localised key')
                        sys.exit(0)
                    r = subprocess.run(
                        ['ssh', '-i', key,
                         '-o', 'StrictHostKeyChecking=no',
                         '-o', 'BatchMode=yes',
                         '-T', 'git@github.com'],
                        capture_output=True, text=True, timeout=15,
                    )
                    # exit 1 = authenticated but no shell (success for deploy keys)
                    # exit 255 = connection/auth failure
                    print(f'exit={{r.returncode}}')
                    print(r.stderr[-200:] if r.stderr else 'no stderr')
                """),
            ],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if "SKIP" in output:
            pytest.skip("no localised key available")
        assert "exit=1" in output, f"SSH should authenticate (exit 1), got: {output}"
