#!/usr/bin/env python3
"""Offline tests for update 0002-tdsb-login (no root, no Wi-Fi needed).

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
LIB = os.path.join(HERE, "..", "updates", "0002-tdsb-login", "files", "usr", "local", "lib", "school-account")
sys.path.insert(0, LIB)

import tdsb_wifi  # noqa: E402


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), os.path.join(LIB, name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


pam_auth = load_script("tdsb-pam-auth")


def fake_account(name, uid=1050, home=None):
    return types.SimpleNamespace(pw_name=name, pw_uid=uid, pw_dir=home or f"/home/{name}")


class StudentIdRules(unittest.TestCase):

    def test_student_ids_are_exactly_nine_digits(self):
        self.assertTrue(tdsb_wifi.is_student_id("123456789"))
        for bad in ("12345678", "1234567890", "12345678a", " 123456789", "", None, "１２３４５６７８９"):
            self.assertFalse(tdsb_wifi.is_student_id(bad), bad)

    def test_username_mapping(self):
        self.assertEqual(tdsb_wifi.username_for("123456789"), "s123456789")
        self.assertEqual(tdsb_wifi.student_id_for("s123456789"), "123456789")
        for other in ("administrator", "teststudent", "studenttwo", "s12345678", "x123456789", "s123456789x"):
            self.assertIsNone(tdsb_wifi.student_id_for(other), other)


class ConnectionSettings(unittest.TestCase):

    def test_matches_tdsb_wifi_instructions(self):
        s = tdsb_wifi.connection_settings("x", "123456789", "pw", autoconnect=True, owner="s123456789")
        self.assertEqual(bytes(s["802-11-wireless"]["ssid"]), b"TDSB-WIFI")
        self.assertEqual(s["802-11-wireless-security"]["key-mgmt"], "wpa-eap")
        self.assertEqual(list(s["802-1x"]["eap"]), ["peap"])
        self.assertEqual(s["802-1x"]["phase2-auth"], "mschapv2")
        self.assertEqual(s["802-1x"]["identity"], "123456789")
        self.assertFalse(s["802-1x"]["system-ca-certs"])
        self.assertNotIn("ca-cert", s["802-1x"])
        self.assertEqual(list(s["connection"]["permissions"]), ["user:s123456789:"])

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
            for user in ("administrator", "teststudent", "studenttwo", "root", "s12345678"):
                accounts = {user: fake_account(user, uid=0 if user == "root" else 1000)}
                self.assertEqual(self.run_main("fallback", user, accounts=accounts), 1, user)
            check.assert_not_called()

    def test_fallback_rejects_when_wifi_rejects(self):
        accounts = {"s123456789": fake_account("s123456789")}
        with mock.patch.object(pam_auth, "has_sessions", return_value=False), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials", return_value=False), \
             mock.patch.object(pam_auth.subprocess, "run") as run:
            self.assertEqual(self.run_main("fallback", "s123456789", accounts=accounts), 1)
            run.assert_not_called()

    def test_fallback_rejects_when_wifi_unavailable(self):
        accounts = {"s123456789": fake_account("s123456789")}
        with mock.patch.object(pam_auth, "has_sessions", return_value=False), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials",
                               side_effect=tdsb_wifi.WifiError("not in range")):
            self.assertEqual(self.run_main("fallback", "s123456789", accounts=accounts), 1)

    def test_fallback_accepts_and_updates_password_when_wifi_accepts(self):
        accounts = {"s123456789": fake_account("s123456789")}
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(pam_auth, "has_sessions", return_value=False), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials", return_value=True) as check, \
             mock.patch.object(pam_auth.subprocess, "run", return_value=ok) as run, \
             mock.patch.object(pam_auth, "retire_login_keyring") as retire:
            self.assertEqual(self.run_main("fallback", "s123456789", "new pass", accounts), 0)
            check.assert_called_once_with("123456789", "new pass")
            self.assertEqual(run.call_args.kwargs["input"], "s123456789:new pass\n")
            retire.assert_called_once_with("s123456789")

    def test_fallback_skipped_while_student_is_logged_in(self):
        accounts = {"s123456789": fake_account("s123456789")}
        with mock.patch.object(pam_auth, "has_sessions", return_value=True), \
             mock.patch.object(pam_auth.tdsb_wifi, "check_credentials") as check:
            self.assertEqual(self.run_main("fallback", "s123456789", accounts=accounts), 1)
            check.assert_not_called()

    def test_connect_always_succeeds_and_only_for_students(self):
        accounts = {"s123456789": fake_account("s123456789"), "administrator": fake_account("administrator", 1000)}
        with mock.patch.object(pam_auth.tdsb_wifi, "add_session_connection") as add:
            self.assertEqual(self.run_main("connect", "administrator", accounts=accounts), 0)
            add.assert_not_called()
            self.assertEqual(self.run_main("connect", "s123456789", "pw", accounts), 0)
            add.assert_called_once_with("s123456789", "pw")

        with mock.patch.object(pam_auth.tdsb_wifi, "add_session_connection", side_effect=RuntimeError("NM down")):
            self.assertEqual(self.run_main("connect", "s123456789", accounts=accounts), 0)

    def test_session_detection_counts_only_desktop_sessions(self):
        listing = (
            "  3 1050 s123456789 seat0 4773 user    tty2 no -\n"
            "  4 1051 s987654321 -     4793 manager -    no -\n"
        )
        with mock.patch.object(pam_auth.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, listing, "")):
            self.assertTrue(pam_auth.has_sessions("s123456789"))
            self.assertFalse(pam_auth.has_sessions("s987654321"))


class PamFile(unittest.TestCase):

    def test_only_common_auth_line_was_replaced(self):
        path = os.path.join(HERE, "..", "updates", "0002-tdsb-login", "files", "etc", "pam.d", "gdm-password")
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
