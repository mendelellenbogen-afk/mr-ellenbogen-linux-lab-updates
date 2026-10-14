#!/usr/bin/env python3
"""Proves one TDSB ID can only ever have one account per laptop.

Runs the REAL create-student script from 0003-tdsb-login with the system tools
it calls (id, adduser, chpasswd, usermod, chown, userdel) swapped for fakes
that record what happens. No root needed, nothing on this computer changes.

    python3 -I update-repo/tests/test_no_duplicate_accounts.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "updates", "0003-tdsb-login", "files", "usr", "local", "lib", "school-account")
sys.path.insert(0, LIB)

import tdsb_wifi  # noqa: E402

TOOLS = {
    "/usr/bin/id": "id",
    "/usr/sbin/adduser": "adduser",
    "/usr/sbin/chpasswd": "chpasswd",
    "/usr/sbin/usermod": "usermod",
    "/usr/bin/chown": "chown",
    "/usr/sbin/userdel": "userdel",
}


class NoDuplicateAccounts(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.accounts = os.path.join(self.dir, "accounts")   # fake /etc/passwd: one name per line
        self.calls = os.path.join(self.dir, "calls")
        open(self.accounts, "w").close()
        open(self.calls, "w").close()

        for tool in TOOLS.values():
            path = os.path.join(self.dir, tool)
            with open(path, "w") as fake:
                fake.write(f'#!/bin/bash\necho "{tool} $*" >> "{self.calls}"\n')
                if tool == "id":
                    fake.write(f'grep -qx "${{@: -1}}" "{self.accounts}"\n')
                elif tool == "adduser":
                    # Real adduser also refuses an existing name.
                    fake.write(f'grep -qx "${{@: -1}}" "{self.accounts}" && exit 1\n')
                    fake.write(f'echo "${{@: -1}}" >> "{self.accounts}"\n')
                else:
                    fake.write("cat > /dev/null\n" if tool == "chpasswd" else "")
            os.chmod(path, 0o755)

        with open(os.path.join(LIB, "create-student")) as script:
            source = script.read()
        for real, tool in TOOLS.items():
            source = source.replace(f'"{real}"', f'"{os.path.join(self.dir, tool)}"')
        source = source.replace('os.path.join("/home", username, "CS")',
                                f'os.path.join("{self.dir}", "home", username, "CS")')
        self.script = os.path.join(self.dir, "create-student")
        with open(self.script, "w") as script:
            script.write(source)

    def create(self, login_id):
        return subprocess.run([sys.executable, "-I", self.script, login_id],
                              input="password\n", capture_output=True, text=True)

    def accounts_made(self):
        with open(self.accounts) as accounts:
            return accounts.read().split()

    def test_second_attempt_with_same_id_is_refused(self):
        self.assertEqual(self.create("123456789").returncode, 0)
        second = self.create("123456789")
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already exists", second.stderr)
        self.assertEqual(self.accounts_made(), ["tdsb-123456789"])

    def test_staff_id_duplicate_refused(self):
        self.assertEqual(self.create("123456").returncode, 0)
        self.assertNotEqual(self.create("123456").returncode, 0)
        self.assertEqual(self.accounts_made(), ["tdsb-123456"])

    def test_same_id_in_different_capitals_is_the_same_account(self):
        self.assertEqual(self.create("ABC123").returncode, 0)
        for variant in ("abc123", "Abc123", "aBC123"):
            self.assertNotEqual(self.create(variant).returncode, 0, variant)
        self.assertEqual(self.accounts_made(), ["tdsb-abc123"])

    def test_refused_attempt_never_calls_adduser(self):
        self.create("123456789")
        open(self.calls, "w").close()
        self.create("123456789")
        with open(self.calls) as calls:
            self.assertEqual([c.split()[0] for c in calls if c.strip()], ["id"])

    def test_account_name_is_derived_only_from_the_id(self):
        # Every spelling that maps to the same account name is treated as one person.
        self.assertEqual(tdsb_wifi.username_for("ABC123"), tdsb_wifi.username_for("abc123"))
        self.assertNotEqual(tdsb_wifi.username_for("123456"), tdsb_wifi.username_for("123456789"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
