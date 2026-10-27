#!/usr/bin/env python3
"""Offline tests for update 0050 (no root needed): which accounts the login
screen's "Admin: clear student accounts" deletes, the administrator password
check, logging students out, and the service's lockout and tokens.

    python3 -I update-repo/tests/test_0050_clear_student_accounts.py
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
UPDATE = os.path.join(HERE, "..", "updates", "0050-clear-student-accounts")
LIB = os.path.join(UPDATE, "files", "usr", "local", "lib", "school-account")
EXTENSION = os.path.join(UPDATE, "files", "usr", "share", "gnome-shell", "extensions",
                         "school-account@school.local", "extension.js")

sys.path.insert(0, LIB)
import clear_accounts  # noqa: E402

loader = importlib.machinery.SourceFileLoader("clear_service", os.path.join(LIB, "clear-accounts-service.py"))
spec = importlib.util.spec_from_loader("clear_service", loader)
service = importlib.util.module_from_spec(spec)
loader.exec_module(service)   # the bus is only touched under __main__


def account(name, uid, home=None, shell="/bin/bash"):
    return types.SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=uid,
                                 pw_dir=home or f"/home/{name}", pw_shell=shell)


LAPTOP = [
    account("root", 0, home="/root"),
    account("gdm", 120, home="/var/lib/gdm3", shell="/bin/false"),
    account("administrator", 1000),
    account("studenttest1", 1001),
    account("studenttest2", 1002),
    account("tdsb-123456789", 1003),
    account("tdsb-654321", 1004),
    account("oldkid", 1005),
    account("odd-home", 1006, home="/srv/odd"),
    account("service", 1007, shell="/usr/sbin/nologin"),
    account("nobody", 65534, home="/nonexistent", shell="/usr/sbin/nologin"),
]


class WhichAccounts(unittest.TestCase):

    def test_keeps_admin_and_test_accounts_deletes_the_rest(self):
        to_delete, skipped = clear_accounts.accounts_to_clear(LAPTOP)
        self.assertEqual([a.pw_name for a in to_delete], ["oldkid", "tdsb-123456789", "tdsb-654321"])
        self.assertEqual([a.pw_name for a in skipped], ["odd-home"])

    def test_nothing_to_delete(self):
        to_delete, skipped = clear_accounts.accounts_to_clear(LAPTOP[:5])
        self.assertEqual((to_delete, skipped), ([], []))


class AdminPassword(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.shadow = os.path.join(self.dir, "shadow")
        patcher = mock.patch.object(clear_accounts, "SHADOW", self.shadow)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_shadow(self, admin_hash):
        with open(self.shadow, "w") as shadow:
            shadow.write("root:*:20000:0:99999:7:::\n")
            shadow.write(f"administrator:{admin_hash}:20000:0:99999:7:::\n")
            shadow.write("tdsb-1:$6$x$y:20000:0:99999:7:::\n")

    def make_hash(self, password):
        return subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=password,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_right_and_wrong_password(self):
        self.write_shadow(self.make_hash("correct horse battery staple"))
        self.assertTrue(clear_accounts.check_admin_password("correct horse battery staple"))
        self.assertFalse(clear_accounts.check_admin_password("correct horse battery"))
        self.assertFalse(clear_accounts.check_admin_password(""))

    def test_locked_or_missing_admin_never_matches(self):
        self.write_shadow("!" + self.make_hash("pw"))
        self.assertFalse(clear_accounts.check_admin_password("pw"))
        self.write_shadow("*")
        self.assertFalse(clear_accounts.check_admin_password("*"))
        os.unlink(self.shadow)
        self.assertFalse(clear_accounts.check_admin_password("pw"))


class Deleting(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.markers = [os.path.join(self.dir, d) for d in ("run", "scheduled", "users", "icons")]
        for directory in self.markers:
            os.makedirs(directory)
            open(os.path.join(directory, "tdsb-123456789"), "w").close()
        self.calls = []
        self.running = set()
        self.stubborn = set()
        self.userdel_code = 0

    def fake_run(self, args, **kwargs):
        program = os.path.basename(args[0])
        self.calls.append([program] + list(args[1:]))
        if program == "pgrep":
            return subprocess.CompletedProcess(args, 0 if int(args[-1]) in self.running else 1)
        if program == "loginctl":
            self.running -= {int(args[-1])} - self.stubborn
        if program == "pkill":
            self.running.discard(int(args[-1]))
        if program == "userdel":
            return subprocess.CompletedProcess(args, self.userdel_code, "", "userdel: boom")
        return subprocess.CompletedProcess(args, 0, "", "")

    def run_clear(self, accounts):
        log = []
        with mock.patch.object(clear_accounts.subprocess, "run", side_effect=self.fake_run), \
             mock.patch.object(clear_accounts.time, "sleep"), \
             mock.patch.object(clear_accounts, "MARKER_DIRS", tuple(self.markers)), \
             mock.patch.object(clear_accounts, "LOGOUT_WAIT", 0), \
             mock.patch.object(clear_accounts, "KILL_WAIT", 0), \
             mock.patch.object(clear_accounts.pwd, "getpwall", return_value=accounts):
            message = clear_accounts.clear_all(log.append)
        return message, log

    def programs(self, name):
        return [call for call in self.calls if call[0] == name]

    def test_deletes_every_student_and_their_markers(self):
        message, _log = self.run_clear(LAPTOP)
        self.assertEqual(message, "Deleted 3 accounts. Left 1 with an unusual home folder alone.")
        self.assertEqual(self.programs("userdel"), [["userdel", "--remove", "oldkid"],
                                                    ["userdel", "--remove", "tdsb-123456789"],
                                                    ["userdel", "--remove", "tdsb-654321"]])
        self.assertEqual(self.programs("loginctl"), [])
        for directory in self.markers:
            self.assertEqual(os.listdir(directory), [])

    def test_logged_in_student_is_logged_out_then_deleted(self):
        self.running = {1003}
        message, log = self.run_clear(LAPTOP[:6])
        self.assertEqual(message, "Deleted 1 account.")
        self.assertEqual(self.programs("loginctl"), [["loginctl", "terminate-user", "1003"]])
        self.assertEqual(self.programs("pkill"), [])
        self.assertIn("Logging out 'tdsb-123456789'.", log)

    def test_processes_that_survive_logout_are_killed(self):
        self.running = {1003}
        self.stubborn = {1003}
        message, _log = self.run_clear(LAPTOP[:6])
        self.assertEqual(message, "Deleted 1 account.")
        self.assertEqual(self.programs("pkill"), [["pkill", "-KILL", "-u", "1003"]])

    def test_userdel_failure_is_reported_and_markers_kept(self):
        self.userdel_code = 1
        message, log = self.run_clear(LAPTOP[:6])
        self.assertEqual(message, "Deleted 0 accounts. Could not delete 1 (see the laptop's journal).")
        self.assertTrue(any("boom" in line for line in log))
        self.assertEqual(os.listdir(self.markers[0]), ["tdsb-123456789"])

    def test_admin_and_test_accounts_are_never_touched(self):
        self.running = {1000, 1001, 1002}
        self.run_clear(LAPTOP[:5])
        self.assertEqual(self.calls, [])


class Service(unittest.TestCase):

    def fake_service(self):
        return types.SimpleNamespace(tokens={}, wrong=0, locked_until=0.0)

    def check(self, svc, password_ok, sender=":1.5"):
        with mock.patch.object(service.clear_accounts, "check_admin_password", return_value=password_ok), \
             mock.patch.object(service.clear_accounts, "accounts_to_clear",
                               return_value=([LAPTOP[5], LAPTOP[6]], [])), \
             mock.patch.object(service.clear_accounts, "has_processes", side_effect=lambda uid: uid == 1003), \
             mock.patch.object(service.time, "sleep"):
            return service.ClearAccountsService.check(svc, "pw", sender)

    def test_right_password_gives_count_and_token(self):
        svc = self.fake_service()
        ok, message, token, count, logged_in = self.check(svc, True)
        self.assertEqual((ok, message, count, logged_in), (True, "OK", 2, 1))
        self.assertEqual(len(token), 32)

    def test_five_wrong_passwords_lock_it(self):
        svc = self.fake_service()
        for _ in range(4):
            self.assertEqual(self.check(svc, False)[1], "That is not the administrator password.")
        self.assertIn("Too many wrong passwords", self.check(svc, False)[1])
        # Even the right password is refused while locked.
        self.assertFalse(self.check(svc, True)[0])

    def test_token_is_single_use_and_tied_to_the_caller(self):
        svc = self.fake_service()
        token = self.check(svc, True)[2]
        with mock.patch.object(service.clear_accounts, "clear_all", return_value="Deleted 2 accounts.") as clear:
            self.assertIn("took too long", service.ClearAccountsService.clear(svc, token, ":1.9")[0])
            token = self.check(svc, True)[2]
            self.assertEqual(service.ClearAccountsService.clear(svc, token, ":1.5"), ("Deleted 2 accounts.",))
            self.assertIn("took too long", service.ClearAccountsService.clear(svc, token, ":1.5")[0])
        self.assertEqual(clear.call_count, 1)

    def test_expired_token_is_refused(self):
        svc = self.fake_service()
        token = self.check(svc, True)[2]
        svc.tokens[token] = (":1.5", 0)
        with mock.patch.object(service.clear_accounts, "clear_all") as clear:
            self.assertIn("took too long", service.ClearAccountsService.clear(svc, token, ":1.5")[0])
        clear.assert_not_called()


class Files(unittest.TestCase):

    def test_extension_parses(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        with tempfile.TemporaryDirectory() as directory:
            copy = os.path.join(directory, "extension.mjs")
            shutil.copy(EXTENSION, copy)
            result = subprocess.run(["node", "--check", copy], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extension_keeps_the_tdsb_panel(self):
        with open(EXTENSION) as handle:
            source = handle.read()
        for needed in ("create_tdsb_account", "Login to TDSB to create your account",
                       "_notListedButton", "addClearAccounts(panel)", "'check_admin'", "'clear_accounts'"):
            self.assertIn(needed, source)

    def test_polkit_allows_nobody_by_default(self):
        with open(os.path.join(UPDATE, "files", "usr", "share", "polkit-1", "actions",
                               "com.school.clear-accounts.policy")) as handle:
            policy = handle.read()
        self.assertIn("<allow_active>no</allow_active>", policy)
        self.assertNotIn("auth_admin", policy)


if __name__ == "__main__":
    unittest.main()
