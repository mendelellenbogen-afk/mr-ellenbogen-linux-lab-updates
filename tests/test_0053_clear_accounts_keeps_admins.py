#!/usr/bin/env python3
"""Tests for update 0053: "Admin: clear student accounts" keeps admin
(sudo-group) accounts. Reruns every 0050 test on the new clear_accounts.py
(with only administrator in the sudo group), plus the new rule. No root needed.

    python3 -I update-repo/tests/test_0053_clear_accounts_keeps_admins.py
"""

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "updates", "0053-clear-accounts-keeps-admins",
                   "files", "usr", "local", "lib", "school-account")

# Load 0053's module first: the 0050 tests (and the 0050 service) then import it.
sys.path.insert(0, LIB)
import clear_accounts  # noqa: E402
assert os.path.dirname(os.path.abspath(clear_accounts.__file__)) == os.path.abspath(LIB)

REAL_ADMIN_NAMES = clear_accounts.admin_names
clear_accounts.admin_names = lambda: ({"administrator"}, 27)

spec = importlib.util.spec_from_file_location("test_0050", os.path.join(HERE, "test_0050_clear_student_accounts.py"))
t50 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t50)
assert t50.clear_accounts is clear_accounts

for _name in dir(t50):
    _obj = getattr(t50, _name)
    if isinstance(_obj, type) and issubclass(_obj, unittest.TestCase) and _obj is not unittest.TestCase:
        globals()[f"From0050_{_name}"] = _obj

account = t50.account
LAPTOP = t50.LAPTOP + [account("mohammad.saleem", 1008)]


class KeepsAdmins(unittest.TestCase):

    def names(self, accounts, admins):
        to_delete, _skipped = clear_accounts.accounts_to_clear(accounts, admins)
        return [a.pw_name for a in to_delete]

    def test_admin_account_is_kept(self):
        self.assertEqual(self.names(LAPTOP, ({"administrator", "mohammad.saleem"}, 27)),
                         ["oldkid", "tdsb-123456789", "tdsb-654321"])

    def test_not_in_sudo_is_deleted(self):
        self.assertIn("mohammad.saleem", self.names(LAPTOP, ({"administrator"}, 27)))

    def test_sudo_as_primary_group_is_kept(self):
        accounts = [account("boss", 1009)]
        accounts[0].pw_gid = 27
        self.assertEqual(self.names(accounts, (set(), 27)), [])

    def test_no_sudo_group(self):
        self.assertEqual(self.names([account("kid", 1009)], (set(), None)), ["kid"])

    def test_real_lookup_returns_names_and_gid(self):
        members, gid = REAL_ADMIN_NAMES()
        self.assertIsInstance(members, set)
        self.assertTrue(gid is None or isinstance(gid, int))


if __name__ == "__main__":
    unittest.main(verbosity=2)
