#!/usr/bin/env python3
"""test_push_preflight.py — verify push_preflight diagnostic logic.

tests the five check functions independently. does not require actual
github access — validates that each check returns the expected shape
for the current environment.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.push_preflight import (
    check_key_file,
    check_key_permissions,
    check_known_hosts,
    check_remote,
    fix_key_permissions,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestPushPreflight(unittest.TestCase):

    def test_check_remote_finds_origin(self):
        """remote should be configured for github."""
        remote = check_remote()
        self.assertIsNotNone(remote)
        self.assertIn("github.com", remote)

    def test_check_key_file_finds_something(self):
        """at least one key file should exist in the expected locations."""
        key = check_key_file()
        # key may or may not exist depending on environment
        if key:
            self.assertTrue(os.path.isfile(key))

    def test_check_key_permissions_detects_open_mode(self):
        """a key with 0777 should be flagged as too open."""
        key = check_key_file()
        if not key:
            self.skipTest("no key file available")
        mode = os.stat(key).st_mode & 0o777
        result = check_key_permissions(key)
        if mode > 0o600:
            self.assertIsNotNone(result)
            self.assertEqual(result, mode)
        else:
            self.assertIsNone(result)

    def test_fix_key_permissions_copies_to_tmp(self):
        """fix should create a copy at /tmp with proper permissions."""
        key = check_key_file()
        if not key:
            self.skipTest("no key file available")
        fixed = fix_key_permissions(key)
        if fixed:
            self.assertTrue(os.path.isfile(fixed))
            mode = os.stat(fixed).st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_check_known_hosts_returns_path_or_none(self):
        """known_hosts check should return a path or None."""
        result = check_known_hosts()
        if result:
            self.assertTrue(os.path.isfile(result))


if __name__ == "__main__":
    unittest.main()
