#!/usr/bin/env python3
"""Tests for 0015-keep-wifi-for-teacher-accounts (school-forget-wifi).
nmcli and loginctl are replaced by a fake over a JSON file. No root, no network.

    python3 -I update-repo/tests/test_0015_keep_wifi.py
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "updates", "0015-keep-wifi-for-teacher-accounts", "files")
FORGET = os.path.join(FILES, "usr", "local", "sbin", "school-forget-wifi")
KEEP_FILE = os.path.join(FILES, "etc", "school-account", "wifi-keep-accounts")

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
name = os.path.basename(sys.argv[0])
if name == "loginctl":
    for i, (user, cls) in enumerate(state["sessions"]):
        print(f"{i + 2} 100{i} {user} seat0 12{i} {cls} tty{i + 2} no -")
    sys.exit(0)
conns = state["connections"]
if args[:4] == ["-t", "-f", "UUID,TYPE", "connection"]:
    for uuid, c in conns.items():
        print(f"{uuid}:{c['type']}")
elif args[:3] == ["-e", "no", "-g"] and args[3] == "connection.permissions":
    users = conns[args[-1]]["users"]
    print(",".join(f"user:{u}" + state.get("suffix", "") for u in users))
elif args[:2] == ["connection", "modify"]:
    conns[args[3]]["users"] = [p.split(":")[1] for p in args[5].split(",")]
elif args[:2] == ["connection", "delete"]:
    del conns[args[3]]
else:
    sys.exit("fake nmcli: unexpected " + " ".join(args))
json.dump(state, open(state_path, "w"))
'''

KEEPERS = ["administrator", "studenttest1", "studenttest2"]


class KeepWifi(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for tool in ("nmcli", "loginctl"):
            path = os.path.join(self.dir, tool)
            with open(path, "w") as tool_file:
                tool_file.write(FAKE)
            os.chmod(path, 0o755)
        self.state_path = os.path.join(self.dir, "state.json")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_forget(self, state, *args, skip=False):
        with open(self.state_path, "w") as state_file:
            json.dump(state, state_file)
        skip_file = os.path.join(self.dir, "skip")
        if skip:
            open(skip_file, "w").close()
        env = dict(os.environ, FAKE_STATE=self.state_path,
                   SCHOOL_NMCLI=os.path.join(self.dir, "nmcli"),
                   SCHOOL_LOGINCTL=os.path.join(self.dir, "loginctl"),
                   SCHOOL_WIFI_KEEP_FILE=KEEP_FILE, SCHOOL_FORGET_SKIP=skip_file)
        result = subprocess.run(["bash", FORGET, *args], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(self.state_path) as state_file:
            return json.load(state_file)["connections"]

    def state(self, sessions, **connections):
        return {"sessions": sessions, "connections": {
            uuid: {"type": "802-11-wireless", "users": users} for uuid, users in connections.items()}}

    def test_teacher_network_is_claimed_and_kept(self):
        left = self.run_forget(self.state([["administrator", "user"]], home=[]))
        self.assertEqual(left, {"home": {"type": "802-11-wireless", "users": KEEPERS}})

    def test_claim_needs_only_keepers_logged_in(self):
        state = self.state([["administrator", "user"], ["tdsb-123456789", "user"]], cafe=[])
        self.assertEqual(self.run_forget(state, "--claim-only")["cafe"]["users"], [])

    def test_claim_ignores_login_screen_and_background_sessions(self):
        state = self.state([["studenttest1", "user"], ["gdm-greeter", "greeter"], ["tdsb-1", "manager"]], net=[])
        self.assertEqual(self.run_forget(state, "--claim-only")["net"]["users"], KEEPERS)

    def test_nobody_logged_in_claims_nothing(self):
        self.assertEqual(self.run_forget(self.state([], net=[]), "--claim-only")["net"]["users"], [])

    def test_student_logout_forgets_student_networks_keeps_teacher_ones(self):
        state = self.state([], kept=KEEPERS, student_home=[], tdsb=["tdsb-123456789"])
        self.assertEqual(list(self.run_forget(state, "--no-claim")), ["kept"])

    def test_mixed_permissions_are_not_kept(self):
        state = self.state([], mixed=["administrator", "tdsb-123456789"])
        self.assertEqual(self.run_forget(state, "--no-claim"), {})

    def test_student_session_never_claims(self):
        # Suspend/shutdown during a student session: everything unrestricted goes.
        state = self.state([["tdsb-123456789", "user"]], home=[], kept=KEEPERS)
        self.assertEqual(list(self.run_forget(state)), ["kept"])

    def test_all_forgets_everything_for_imaging(self):
        state = self.state([["administrator", "user"]], kept=KEEPERS, other=[])
        self.assertEqual(self.run_forget(state, "--all"), {})

    def test_all_ignores_skip_file(self):
        state = self.state([], kept=KEEPERS)
        self.assertEqual(self.run_forget(state, "--all", skip=True), {})

    def test_skip_file_skips_once(self):
        state = self.state([], net=[])
        self.assertIn("net", self.run_forget(state, skip=True))
        self.assertNotIn("net", self.run_forget(state))

    def test_ethernet_untouched(self):
        state = self.state([], wifi=[])
        state["connections"]["wired"] = {"type": "802-3-ethernet", "users": []}
        self.assertEqual(list(self.run_forget(state, "--all")), ["wired"])

    def test_permissions_with_trailing_colon_format(self):
        state = self.state([], kept=KEEPERS)
        state["suffix"] = ":"
        self.assertEqual(list(self.run_forget(state, "--no-claim")), ["kept"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
