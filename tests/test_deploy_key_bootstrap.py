"""Tests for iamai.deploy_key_bootstrap — SSH deploy key generation and config."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.deploy_key_bootstrap import (
    KeyState,
    Action,
    BootstrapResult,
    bootstrap,
    format_instructions,
    _key_exists,
    _key_writable,
    _read_public_key,
    _ssh_config_ok,
    _write_ssh_config,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ssh_env(tmp_path):
    """Create a clean ssh dir and key path for testing."""
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir(mode=0o700)
    key_path = ssh_dir / "id_ed25519"
    return ssh_dir, key_path


def _make_key(key_path: Path, pub_content: str = "ssh-ed25519 AAAA... test@host"):
    """Create fake key pair files."""
    key_path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n")
    key_path.chmod(0o600)
    pub = key_path.with_suffix(key_path.suffix + ".pub")
    pub.write_text(pub_content)
    pub.chmod(0o644)


def _make_ssh_config(ssh_dir: Path, key_path: Path):
    """Create a valid ssh config for the key."""
    config = ssh_dir / "config"
    config.write_text(
        f"Host github.com\n"
        f"    IdentityFile {key_path}\n"
        f"    IdentitiesOnly yes\n"
    )
    config.chmod(0o600)


# ---------------------------------------------------------------------------
# _key_exists tests
# ---------------------------------------------------------------------------

class TestKeyExists:
    def test_both_missing(self, tmp_path):
        assert _key_exists(tmp_path / "nope") is False

    def test_private_only(self, tmp_path):
        kp = tmp_path / "key"
        kp.write_text("private")
        assert _key_exists(kp) is False

    def test_pub_only(self, tmp_path):
        kp = tmp_path / "key"
        pub = tmp_path / "key.pub"
        pub.write_text("pub")
        assert _key_exists(kp) is False

    def test_both_present(self, tmp_path):
        kp = tmp_path / "key"
        _make_key(kp)
        assert _key_exists(kp) is True

    def test_empty_private(self, tmp_path):
        kp = tmp_path / "key"
        kp.write_text("")  # empty
        pub = tmp_path / "key.pub"
        pub.write_text("pub")
        assert _key_exists(kp) is False

    def test_empty_pub(self, tmp_path):
        kp = tmp_path / "key"
        kp.write_text("private")
        pub = tmp_path / "key.pub"
        pub.write_text("")
        assert _key_exists(kp) is False


# ---------------------------------------------------------------------------
# _key_writable tests
# ---------------------------------------------------------------------------

class TestKeyWritable:
    def test_parent_exists_and_writable(self, tmp_path):
        assert _key_writable(tmp_path / "key") is True

    def test_parent_missing_but_creatable(self, tmp_path):
        sub = tmp_path / "a" / "b"
        assert _key_writable(sub / "key") is True

    def test_parent_readonly(self, tmp_path):
        ro = tmp_path / "readonly"
        ro.mkdir()
        ro.chmod(0o555)
        with patch("iamai.deploy_key_bootstrap.os.access", return_value=False):
            result = _key_writable(ro / "key")
        ro.chmod(0o755)  # cleanup so tmp can be removed
        assert result is False


# ---------------------------------------------------------------------------
# _ssh_config_ok tests
# ---------------------------------------------------------------------------

class TestSshConfigOk:
    def test_no_config(self, tmp_path):
        assert _ssh_config_ok(tmp_path, tmp_path / "key") is False

    def test_config_no_github(self, tmp_path):
        config = tmp_path / "config"
        config.write_text("Host other.com\n    IdentityFile /some/key\n")
        assert _ssh_config_ok(tmp_path, tmp_path / "key") is False

    def test_config_github_wrong_key(self, tmp_path):
        config = tmp_path / "config"
        config.write_text("Host github.com\n    IdentityFile /wrong/path\n")
        assert _ssh_config_ok(tmp_path, tmp_path / "key") is False

    def test_config_github_correct(self, ssh_env):
        ssh_dir, key_path = ssh_env
        _make_ssh_config(ssh_dir, key_path)
        assert _ssh_config_ok(ssh_dir, key_path) is True


# ---------------------------------------------------------------------------
# _write_ssh_config tests
# ---------------------------------------------------------------------------

class TestWriteSshConfig:
    def test_creates_new(self, ssh_env):
        ssh_dir, key_path = ssh_env
        assert _write_ssh_config(ssh_dir, key_path) is True
        config = ssh_dir / "config"
        assert config.exists()
        text = config.read_text()
        assert "Host github.com" in text
        assert str(key_path) in text
        # permissions
        assert oct(config.stat().st_mode & 0o777) == "0o600"

    def test_preserves_existing(self, ssh_env):
        ssh_dir, key_path = ssh_env
        config = ssh_dir / "config"
        config.write_text("Host other.com\n    IdentityFile /other/key\n")
        assert _write_ssh_config(ssh_dir, key_path) is True
        text = config.read_text()
        assert "Host other.com" in text
        assert "Host github.com" in text

    def test_replaces_old_block(self, ssh_env):
        ssh_dir, key_path = ssh_env
        config = ssh_dir / "config"
        config.write_text(
            "# Added by deploy_key_bootstrap\n"
            "Host github.com\n"
            "    IdentityFile /old/path\n"
            "    IdentitiesOnly yes\n"
            "    StrictHostKeyChecking accept-new\n"
        )
        assert _write_ssh_config(ssh_dir, key_path) is True
        text = config.read_text()
        assert "/old/path" not in text
        assert str(key_path) in text


# ---------------------------------------------------------------------------
# bootstrap integration tests (mocked ssh-keygen)
# ---------------------------------------------------------------------------

class TestBootstrap:
    def test_missing_key_generates(self, ssh_env):
        ssh_dir, key_path = ssh_env
        fake_pub = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake test@iamai"

        with patch("iamai.deploy_key_bootstrap._generate_key", return_value=True), \
             patch("iamai.deploy_key_bootstrap._read_public_key", return_value=fake_pub), \
             patch("iamai.deploy_key_bootstrap._extract_fingerprint", return_value="SHA256:fake"):
            result = bootstrap(key_path=key_path, ssh_dir=ssh_dir)

        assert result.state == KeyState.MISSING
        assert result.action == Action.GENERATED
        assert result.public_key == fake_pub
        assert result.ssh_config_ok is True

    def test_existing_key_reuses(self, ssh_env):
        ssh_dir, key_path = ssh_env
        _make_key(key_path)
        _make_ssh_config(ssh_dir, key_path)
        fake_pub = "ssh-ed25519 AAAA existing@host"

        with patch("iamai.deploy_key_bootstrap._read_public_key", return_value=fake_pub), \
             patch("iamai.deploy_key_bootstrap._extract_fingerprint", return_value="SHA256:exist"):
            result = bootstrap(key_path=key_path, ssh_dir=ssh_dir)

        assert result.state == KeyState.EXISTS
        assert result.action == Action.REUSED
        assert result.public_key == fake_pub

    def test_orphan_key_fixes_config(self, ssh_env):
        ssh_dir, key_path = ssh_env
        _make_key(key_path)
        # no ssh config file
        fake_pub = "ssh-ed25519 AAAA orphan@host"

        with patch("iamai.deploy_key_bootstrap._read_public_key", return_value=fake_pub), \
             patch("iamai.deploy_key_bootstrap._extract_fingerprint", return_value="SHA256:orph"):
            result = bootstrap(key_path=key_path, ssh_dir=ssh_dir)

        assert result.state == KeyState.ORPHAN
        assert result.action == Action.FIXED_CONFIG
        assert result.ssh_config_ok is True

    def test_keygen_failure_skips(self, ssh_env):
        ssh_dir, key_path = ssh_env

        with patch("iamai.deploy_key_bootstrap._generate_key", return_value=False):
            result = bootstrap(key_path=key_path, ssh_dir=ssh_dir)

        assert result.state == KeyState.MISSING
        assert result.action == Action.SKIPPED
        assert "ssh-keygen failed" in result.reason

    def test_readonly_dir_skips(self, tmp_path):
        ro = tmp_path / "locked"
        ro.mkdir()
        key_path = ro / "id_ed25519"

        with patch("iamai.deploy_key_bootstrap._key_writable", return_value=False):
            result = bootstrap(key_path=key_path, ssh_dir=ro)

        assert result.action == Action.SKIPPED


# ---------------------------------------------------------------------------
# format_instructions tests
# ---------------------------------------------------------------------------

class TestFormatInstructions:
    def test_skipped(self):
        r = BootstrapResult(
            state=KeyState.READONLY,
            action=Action.SKIPPED,
            key_path=Path("/no/key"),
            reason="permission denied",
        )
        text = format_instructions(r)
        assert "skipped" in text.lower()
        assert "permission denied" in text

    def test_generated(self):
        r = BootstrapResult(
            state=KeyState.MISSING,
            action=Action.GENERATED,
            key_path=Path("/home/user/.ssh/id_ed25519"),
            public_key="ssh-ed25519 AAAA test",
            fingerprint="SHA256:abc",
            ssh_config_ok=True,
        )
        text = format_instructions(r)
        assert "generated" in text
        assert "ssh-ed25519 AAAA test" in text
        assert "Deploy keys" in text

    def test_reused(self):
        r = BootstrapResult(
            state=KeyState.EXISTS,
            action=Action.REUSED,
            key_path=Path("/key"),
            public_key="ssh-ed25519 AAAA",
            fingerprint="SHA256:def",
            ssh_config_ok=True,
        )
        text = format_instructions(r)
        assert "look good" in text
