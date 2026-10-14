#!/usr/bin/env python3
"""Offline tests for update 0004-remove-old-accounts (immediate version, no root).

    python3 -I update-repo/tests/test_0004_remove_old_accounts.py
"""

import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "updates", "0004-remove-old-accounts", "files")
LIB = os.path.join(FILES, "usr", "local", "lib", "school-account")
os.environ["SCHOOL_KEEP_ACCOUNTS"] = os.path.join(FILES, "etc", "school-account", "keep-accounts")
sys.path.insert(0, LIB)

import legacy_accounts  # noqa: E402

loader = importlib.machinery.SourceFileLoader("cleanup", os.path.join(LIB, "legacy-account-cleanup.py"))
spec = importlib.util.spec_from_loader("cleanup", loader)
cleanup = importlib.util.module_from_spec(spec)
loader.exec_module(cleanup)


def account(name, uid=1005, home=None, shell="/bin/bash"):
    return types.SimpleNamespace(pw_name=name, pw_uid=uid, pw_dir=home or f"/home/{name}", pw_shell=shell)


LAPTOP = [
    account("root", 0, "/root"),
    account("gdm", 120, "/var/lib/gdm3", "/bin/false"),
    account("administrator", 1000),
    account("teststudent", 1001),
    account("studenttwo", 1003),
    account("studentone", 1002),
    account("john_smith", 1004),
    account("tdsb-123456789", 1006),
    account("tdsb-123456", 1007),
    account("nobody", 65534, "/nonexistent", "/usr/sbin/nologin"),
]


class Classification(unittest.TestCase):

    def test_only_old_style_accounts_selected(self):
        self.assertEqual([a.pw_name for a in legacy_accounts.legacy_accounts(LAPTOP)], ["john_smith", "studentone"])

    def test_administrator_kept_even_if_keep_file_missing(self):
        with mock.patch.object(legacy_accounts, "KEEP_FILE", "/nonexistent"):
            self.assertFalse(legacy_accounts.is_legacy(account("administrator", 1000)))


class Cleanup(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.list_file = os.path.join(self.dir, "legacy-to-remove")
        self.pending = os.path.join(self.dir, "pending")
        patches = [
            mock.patch.object(legacy_accounts, "REMOVE_LIST", self.list_file),
            mock.patch.object(cleanup, "SELF_DELETE_PENDING", self.pending),
            mock.patch.object(legacy_accounts.pwd, "getpwall", return_value=list(self.laptop())),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def laptop(self, extra=()):
        return LAPTOP + list(extra)

    def run_cleanup(self, accounts=None, sessions="", running=()):
        accounts = {a.pw_name: a for a in (accounts or self.laptop())}
        deleted = []

        def fake_run(args, **kwargs):
            if args[0].endswith("loginctl"):
                return subprocess.CompletedProcess(args, 0, sessions, "")
            if args[0].endswith("pgrep"):
                return subprocess.CompletedProcess(args, 0 if args[2] in running else 1, "", "")
            if args[0].endswith("userdel"):
                deleted.append(args[-1])
            return subprocess.CompletedProcess(args, 0, "", "")

        def getpwnam(name):
            if name in accounts:
                return accounts[name]
            raise KeyError(name)

        with mock.patch.object(cleanup.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(cleanup.pwd, "getpwnam", side_effect=getpwnam):
            cleanup.main()

        return deleted

    def test_snapshot_then_delete_all_old_accounts(self):
        self.assertEqual(legacy_accounts.snapshot_remove_list(), [("john_smith", 1004), ("studentone", 1002)])
        self.assertEqual(self.run_cleanup(), ["john_smith", "studentone"])
        self.assertEqual(legacy_accounts.read_remove_list(), [])

    def test_snapshot_is_taken_only_once(self):
        legacy_accounts.snapshot_remove_list()
        with mock.patch.object(legacy_accounts.pwd, "getpwall", return_value=self.laptop([account("newer", 1010)])):
            self.assertNotIn(("newer", 1010), legacy_accounts.snapshot_remove_list())

    def test_accounts_created_later_are_never_deleted(self):
        legacy_accounts.snapshot_remove_list()
        later = self.laptop([account("guest", 1010)])
        self.assertNotIn("guest", self.run_cleanup(accounts=later))

    def test_logged_in_account_handed_to_delete_after_logout(self):
        legacy_accounts.snapshot_remove_list()
        deleted = self.run_cleanup(sessions="  9 1002 studentone seat0 77 user tty2 no -\n")
        self.assertEqual(deleted, ["john_smith"])
        self.assertEqual(legacy_accounts.read_remove_list(), [("studentone", 1002)])
        with open(os.path.join(self.pending, "studentone")) as marker:
            self.assertEqual(marker.read(), "UID=1002\nUSERNAME=studentone\n")
        self.assertEqual(os.stat(os.path.join(self.pending, "studentone")).st_mode & 0o777, 0o600)

    def test_reused_name_with_new_uid_is_left_alone(self):
        legacy_accounts.snapshot_remove_list()
        replaced = [a for a in self.laptop() if a.pw_name != "studentone"] + [account("studentone", 1099)]
        self.assertEqual(self.run_cleanup(accounts=replaced), ["john_smith"])
        self.assertEqual(legacy_accounts.read_remove_list(), [])

    def test_never_deletes_protected_or_tdsb_accounts(self):
        legacy_accounts.write_remove_list([("administrator", 1000), ("teststudent", 1001), ("tdsb-123456", 1007)])
        self.assertEqual(self.run_cleanup(), [])

    def test_no_list_means_nothing_happens(self):
        self.assertEqual(self.run_cleanup(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
