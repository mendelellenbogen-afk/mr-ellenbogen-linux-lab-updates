#!/usr/bin/env python3
"""Offline tests for update 0003-tdsb-login (no root, no Wi-Fi needed).

    python3 -I update-repo/tests/test_0002_tdsb_login.py

The real Wi-Fi check and login screen can only be tested on the test laptop.
"""

import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "updates", "0003-tdsb-login", "files", "usr", "local", "lib", "school-account")
sys.path.insert(0, LIB)

import tdsb_wifi  # noqa: E402


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), os.path.join(LIB, name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


pam_auth = load_script("tdsb-pam-auth")


def fake_account(name, uid=1050, home=None, gecos=""):
    return types.SimpleNamespace(pw_name=name, pw_uid=uid, pw_dir=home or f"/home/{name}", pw_gecos=gecos)


STUDENT = "tdsb-123456789"


class LoginIdRules(unittest.TestCase):

    def test_student_staff_and_letter_ids_accepted(self):
        for good in ("123456789", "123456", "ABC123", "jsmith", "abc", "a" * 27):
            self.assertTrue(tdsb_wifi.is_login_id(good), good)

    def test_bad_ids_rejected(self):
        for bad in ("12", "a" * 28, "john smith", "j.smith", "name-1", " 123456", "", None,
                    "１２３４５６", "../etc", "root;rm"):
            self.assertFalse(tdsb_wifi.is_login_id(bad), bad)

    def test_account_names(self):
        self.assertEqual(tdsb_wifi.username_for("123456789"), "tdsb-123456789")
        self.assertEqual(tdsb_wifi.username_for("123456"), "tdsb-123456")
        self.assertEqual(tdsb_wifi.username_for("ABC123"), "tdsb-abc123")
        for name in ("tdsb-123456789", "tdsb-123456", "tdsb-abc123"):
            self.assertTrue(tdsb_wifi.is_tdsb_account(name), name)
        for other in ("administrator", "teststudent", "studenttwo", "s123456789", "tdsb-", "tdsb-ABC", "xtdsb-123"):
            self.assertFalse(tdsb_wifi.is_tdsb_account(other), other)

    def test_wifi_identity_keeps_the_case_typed_at_creation(self):
        self.assertEqual(tdsb_wifi.login_id_for("tdsb-abc123", "ABC123"), "ABC123")
        self.assertEqual(tdsb_wifi.login_id_for("tdsb-123456", "123456,,,"), "123456")
        # Full name edited to something else: fall back to the account name.
        self.assertEqual(tdsb_wifi.login_id_for("tdsb-123456", "Mr Smith"), "123456")
        self.assertIsNone(tdsb_wifi.login_id_for("administrator", "Administrator"))


class ConnectionSettings(unittest.TestCase):

    def test_matches_tdsb_wifi_instructions(self):
        s = tdsb_wifi.connection_settings("x", "123456789", "pw", autoconnect=True, owner="tdsb-123456789")
        self.assertEqual(bytes(s["802-11-wireless"]["ssid"]), b"TDSB-WIFI")
        self.assertEqual(s["802-11-wireless-security"]["key-mgmt"], "wpa-eap")
        self.assertEqual(list(s["802-1x"]["eap"]), ["peap"])
        self.assertEqual(s["802-1x"]["phase2-auth"], "mschapv2")
        self.assertEqual(s["802-1x"]["identity"], "123456789")
        self.assertFalse(s["802-1x"]["system-ca-certs"])
        self.assertNotIn("ca-cert", s["802-1x"])
        self.assertEqual(list(s["connection"]["permissions"]), ["user:tdsb-123456789:"])

    def test_verify_connection_has_no_owner_and_no_autoconnect(self):
        s = tdsb_wifi.connection_settings("x", "123456789", "pw", autoconnect=False)
        self.assertNotIn("permissions", s["connection"])
        self.assertFalse(s["connection"]["autoconnect"])


class PamScript(unittest.TestCase):

    def run_main(self, mode, user, password="pw", accounts=None):
        accounts = accounts or {}

        def getpwnam(name):
            if name in accounts:
                return accounts[name]
            raise KeyError(name)

        stdin = types.SimpleNamespace(buffer=io.BytesIO(password.encode() + b"\0"))
        with mock.patch.object(sys, "argv", ["tdsb-pam-auth", mode]), \
             mock.patch.dict(os.environ, {"PAM_USER": user}), \
             mock.patch.object(sys, "stdin", stdin), \
             mock.patch.object(pam_auth.pwd, "getpwnam", side_effect=getpwnam):
            return pam_auth.main()

    def test_fallback_never_handles_non_student_accounts(self):
        with mock.patch.object(pam_auth.tdsb_wifi, "check_credentials") as check:
            for user in ("administrator", "teststudent", "studenttwo", "root", "s123456789", "123456"):
                accounts = {user: fake_account(user, uid=0 if user == "root" else 1000)}
                self.assertEqual(self.run_main("fallback", user, accounts=accounts), 1, user)
            check.assert_not_called()

    def test_fallback_rejects_when_wifi_rejects(self):
        accounts = {STUDENT: fake_account(STUDENT, gecos="123456789")}
        with mock.patch.object(pam_auth, "has_sessions", return_value=False), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials", return_value=False), \
             mock.patch.object(pam_auth.subprocess, "run") as run:
            self.assertEqual(self.run_main("fallback", STUDENT, accounts=accounts), 1)
            run.assert_not_called()

    def test_fallback_rejects_when_wifi_unavailable(self):
        accounts = {STUDENT: fake_account(STUDENT, gecos="123456789")}
        with mock.patch.object(pam_auth, "has_sessions", return_value=False), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials",
                               side_effect=tdsb_wifi.WifiError("not in range")):
            self.assertEqual(self.run_main("fallback", STUDENT, accounts=accounts), 1)

    def test_fallback_accepts_and_updates_password_when_wifi_accepts(self):
        accounts = {STUDENT: fake_account(STUDENT, gecos="123456789")}
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(pam_auth, "has_sessions", return_value=False), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials", return_value=True) as check, \
             mock.patch.object(pam_auth.subprocess, "run", return_value=ok) as run, \
             mock.patch.object(pam_auth, "retire_login_keyring") as retire:
            self.assertEqual(self.run_main("fallback", STUDENT, "new pass", accounts), 0)
            check.assert_called_once_with("123456789", "new pass")
            self.assertEqual(run.call_args.kwargs["input"], "tdsb-123456789:new pass\n")
            retire.assert_called_once_with(STUDENT)

    def test_fallback_skipped_while_student_is_logged_in(self):
        accounts = {STUDENT: fake_account(STUDENT, gecos="123456789")}
        with mock.patch.object(pam_auth, "has_sessions", return_value=True), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials") as check:
            self.assertEqual(self.run_main("fallback", STUDENT, accounts=accounts), 1)
            check.assert_not_called()

    def test_connect_always_succeeds_and_only_for_students(self):
        accounts = {STUDENT: fake_account(STUDENT, gecos="123456789"), "administrator": fake_account("administrator", 1000)}
        with mock.patch.object(pam_auth.tdsb_wifi, "add_session_connection") as add:
            self.assertEqual(self.run_main("connect", "administrator", accounts=accounts), 0)
            add.assert_not_called()
            self.assertEqual(self.run_main("connect", STUDENT, "pw", accounts), 0)
            add.assert_called_once_with(STUDENT, "pw")

        with mock.patch.object(pam_auth.tdsb_wifi, "add_session_connection", side_effect=RuntimeError("NM down")):
            self.assertEqual(self.run_main("connect", STUDENT, accounts=accounts), 0)

    def test_session_detection_counts_only_desktop_sessions(self):
        listing = (
            "  3 1050 tdsb-123456789 seat0 4773 user    tty2 no -\n"
            "  4 1051 tdsb-123456 -     4793 manager -    no -\n"
        )
        with mock.patch.object(pam_auth.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, listing, "")):
            self.assertTrue(pam_auth.has_sessions("tdsb-123456789"))
            self.assertFalse(pam_auth.has_sessions("tdsb-123456"))


class PamFile(unittest.TestCase):

    def test_only_common_auth_line_was_replaced(self):
        path = os.path.join(HERE, "..", "updates", "0003-tdsb-login", "files", "etc", "pam.d", "gdm-password")
        with open(path) as pam_file:
            lines = [l for l in pam_file if l.strip() and not l.startswith("#")]
        auth = [l.split() for l in lines if l.startswith("auth")]
        modules = [next(w for w in parts if w.endswith(".so")) for parts in auth]
        self.assertEqual(modules, [
            "pam_nologin.so", "pam_succeed_if.so", "pam_unix.so", "pam_sss.so", "pam_exec.so",
            "pam_deny.so", "pam_permit.so", "pam_cap.so", "pam_exec.so", "pam_gnome_keyring.so",
        ])
        # Jump targets: unix(+3), sss(+2), fallback(+1) must all land on pam_permit.
        for index, jump in ((2, 3), (3, 2), (4, 1)):
            self.assertIn(f"success={jump}", auth[index][1])
            self.assertEqual(modules[index + jump + 1], "pam_permit.so")


if __name__ == "__main__":
    unittest.main(verbosity=2)
