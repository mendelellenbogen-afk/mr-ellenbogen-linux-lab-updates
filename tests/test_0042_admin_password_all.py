#!/usr/bin/env python3
"""Tests for 0042-admin-password-all: every laptop changes the
administrator password, to exactly the teacher's hash, once; laptops
without the account change nothing. Fakes only (no root).

    python3 -I update-repo/tests/test_0042_admin_password_test.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0042-admin-password-all")
TARGETING = os.path.join(HERE, "..", "updates", "0023-targeted-messages", "files", "usr", "local", "lib",
                         "lab-updater", "targeting.sh")
HASH = "$6$hKlY3/bR6sRg5Hpd$1MwmcclGmtnUjq/.XPiOhkQ2kuBzR3G671G8GP4MUtMikT/OT8FbN/X07QjY1xD/cAJyDz/U6cHIh7t9X.CIK."


class Install(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = lambda *p: os.path.join(self.dir, *p)
        os.makedirs(d("bin"))
        self.shadow = d("shadow")
        with open(d("helpers.sh"), "w") as handle:
            handle.write('set -euo pipefail\nsay() { echo "[test] $*"; }\n')
        shutil.copy(TARGETING, d("targeting.sh"))
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read().replace("/usr/local/lib/lab-updater/targeting.sh", d("targeting.sh"))
        with open(d("install.sh"), "w") as handle:
            handle.write(script)
        self.write("hostname", 'echo "$FAKE_HOST"')
        self.write("getent", f'case "$1" in passwd) [ -s {self.shadow} ];; '
                             f'shadow) [ -s {self.shadow} ] && echo "administrator:$(cat {self.shadow}):20000:0:99999:7:::";; esac')
        self.write("usermod", f'echo "usermod $*" >> {d("calls")}; [ "$1" = -p ] && printf %s "$2" > {self.shadow}')

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, name, body):
        path = os.path.join(self.dir, "bin", name)
        with open(path, "w") as handle:
            handle.write(f"#!/bin/bash\n{body}\n")
        os.chmod(path, 0o755)

    def run_it(self, host, old="$6$old$oldhash"):
        if old is not None:
            with open(self.shadow, "w") as handle:
                handle.write(old)
        env = dict(os.environ, PATH=os.path.join(self.dir, "bin") + ":" + os.environ["PATH"], FAKE_HOST=host,
                   LAB_UPDATER_HELPERS=os.path.join(self.dir, "helpers.sh"))
        return subprocess.run(["bash", os.path.join(self.dir, "install.sh")], env=env, capture_output=True, text=True)

    def calls(self):
        path = os.path.join(self.dir, "calls")
        return open(path).read() if os.path.exists(path) else ""

    def test_the_test_laptop_gets_exactly_the_hash(self):
        done = self.run_it("lab-5cd137htq8")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("administrator password changed", done.stdout)
        with open(self.shadow) as handle:
            self.assertEqual(handle.read(), HASH)
        again = self.run_it("lab-5cd137htq8", old=None)
        self.assertIn("already the new one", again.stdout)
        self.assertEqual(self.calls().count("usermod"), 1)

    def test_every_laptop_changes(self):
        for host in ("lab-5cd137g4vb", "lab-jq8fzm2"):
            done = self.run_it(host)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("administrator password changed", done.stdout)
            with open(self.shadow) as handle:
                self.assertEqual(handle.read(), HASH)

    def test_same_hash_as_0041(self):
        with open(os.path.join(HERE, "..", "updates", "0041-admin-password-test", "install.sh")) as one, \
                open(os.path.join(UPDATE, "install.sh")) as every:
            pick = lambda text: [line for line in text.splitlines() if line.startswith("NEW_HASH=")]
            self.assertEqual(pick(one.read()), pick(every.read()))
            self.assertNotIn("only_on_laptops", every.read())

    def test_no_administrator_account(self):
        done = self.run_it("lab-5cd137htq8", old="")
        self.assertEqual(done.returncode, 0)
        self.assertIn("no administrator account", done.stdout)
        self.assertEqual(self.calls(), "")

    def test_hash_is_sha512_crypt(self):
        parts = HASH.split("$")
        self.assertEqual((parts[1], len(parts[2]), len(parts[3])), ("6", 16, 86))


if __name__ == "__main__":
    unittest.main()
