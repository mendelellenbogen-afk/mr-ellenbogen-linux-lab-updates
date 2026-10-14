#!/usr/bin/env python3
"""Offline tests for update 0005 (no root needed): the "Delete in 7 days" path
of the self-delete worker.

    python3 -I update-repo/tests/test_0005_delete_options.py
"""

import datetime
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "..", "updates", "0005-show-password-and-delete-options", "files",
                      "usr", "local", "lib", "school-account", "self-delete", "self-delete-worker.py")

loader = importlib.machinery.SourceFileLoader("worker", WORKER)
spec = importlib.util.spec_from_loader("worker", loader)
worker = importlib.util.module_from_spec(spec)
loader.exec_module(worker)

TODAY = datetime.date(2026, 10, 14)


class FakeDate(datetime.date):
    @classmethod
    def today(cls):
        return TODAY


class ScheduledDeletion(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.userdel = []

    def marker(self, name="tdsb-123456789", uid=1050, delete_after="2026-10-21", extra=""):
        path = os.path.join(self.dir, name)
        with open(path, "w") as marker:
            marker.write(f"UID={uid}\nUSERNAME={name}\nDELETE_AFTER={delete_after}\n{extra}")
        os.chmod(path, 0o600)
        return path

    def run_worker(self, path, account_uid=1050, sessions="", processes=""):
        account = types.SimpleNamespace(pw_uid=account_uid, pw_dir="/home/tdsb-123456789",
                                        pw_shell="/bin/bash", pw_gid=account_uid)

        def fake_run(args, **kwargs):
            if args[0].endswith("loginctl"):
                return subprocess.CompletedProcess(args, 0, sessions, "")
            if args[0].endswith("pgrep"):
                return subprocess.CompletedProcess(args, 0 if processes else 1, processes, "")
            if args[0].endswith("userdel"):
                self.userdel.append(args[-1])
            return subprocess.CompletedProcess(args, 0, "", "")

        def getpwnam(name):
            if account_uid is None:
                raise KeyError(name)
            return account

        real_stat = os.stat

        def stat_as_root(p, *a, **k):
            result = real_stat(p, *a, **k)
            return types.SimpleNamespace(st_uid=0, st_mode=result.st_mode)

        with mock.patch.object(worker.datetime, "date", FakeDate), \
             mock.patch.object(worker.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(worker.pwd, "getpwnam", side_effect=getpwnam), \
             mock.patch.object(worker.grp, "getgrgid", return_value=types.SimpleNamespace(gr_name="tdsb-123456789")), \
             mock.patch.object(worker.os, "stat", side_effect=stat_as_root):
            worker.process_request(path, scheduled=True)

    def test_not_deleted_before_the_date(self):
        path = self.marker(delete_after="2026-10-21")
        self.run_worker(path)
        self.assertEqual(self.userdel, [])
        self.assertTrue(os.path.exists(path))

    def test_deleted_on_the_date_when_logged_out(self):
        path = self.marker(delete_after="2026-10-14")
        self.run_worker(path)
        self.assertEqual(self.userdel, ["tdsb-123456789"])
        self.assertFalse(os.path.exists(path))

    def test_waits_while_logged_in(self):
        path = self.marker(delete_after="2026-10-01")
        self.run_worker(path, sessions="  5 1050 tdsb-123456789 seat0 99 user tty2 no -\n")
        self.assertEqual(self.userdel, [])
        self.assertTrue(os.path.exists(path))

    def test_stale_request_for_deleted_account_is_discarded(self):
        path = self.marker(delete_after="2026-10-01")
        self.run_worker(path, account_uid=None)
        self.assertEqual(self.userdel, [])
        self.assertFalse(os.path.exists(path))

    def test_old_request_never_deletes_a_new_account_with_the_same_name(self):
        path = self.marker(uid=1050, delete_after="2026-10-01")
        self.run_worker(path, account_uid=1077)
        self.assertEqual(self.userdel, [])
        self.assertFalse(os.path.exists(path))

    def test_protected_accounts_never_deleted(self):
        path = self.marker(name="teststudent", uid=1001, delete_after="2026-10-01")
        self.run_worker(path, account_uid=1001)
        self.assertEqual(self.userdel, [])

    def test_marker_with_unexpected_field_rejected(self):
        path = self.marker(delete_after="2026-10-01", extra="SHELL=/bin/sh\n")
        self.run_worker(path)
        self.assertEqual(self.userdel, [])

    def test_now_markers_still_require_exactly_uid_and_username(self):
        path = self.marker(delete_after="2026-10-01")
        marker, reason = worker.read_marker(path)          # default = "delete now" format
        self.assertIsNone(marker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
