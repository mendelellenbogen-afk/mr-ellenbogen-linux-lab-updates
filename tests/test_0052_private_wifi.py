#!/usr/bin/env python3
"""Tests for 0052-private-wifi-for-admins (school-forget-wifi).
Reruns every 0015 test on the new script, plus private Wi-Fi for other
sudo-group accounts. nmcli, loginctl and getent are fakes. No root, no network.

    python3 -I update-repo/tests/test_0052_private_wifi.py
"""

import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("test_0015", os.path.join(HERE, "test_0015_keep_wifi.py"))
t15 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t15)

FORGET = os.path.join(HERE, "..", "updates", "0052-private-wifi-for-admins",
                      "files", "usr", "local", "sbin", "school-forget-wifi")
KEEPERS = t15.KEEPERS

GETENT = r'''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_STATE"]))
db, key = sys.argv[1], sys.argv[2]
if db == "group" and key == "sudo":
    print("sudo:x:27:" + ",".join(state.get("sudo", [])))
elif db == "passwd" and key in state.get("uids", {}):
    print(f"{key}:x:{state['uids'][key]}:{state['uids'][key]}::/home/{key}:/bin/bash")
else:
    sys.exit(2)
'''


class Shared0015(t15.KeepWifi):
    """The 0015 behaviour, unchanged, with a colleague admin on the laptop."""

    def setUp(self):
        super().setUp()
        t15.FORGET = FORGET
        path = os.path.join(self.dir, "getent")
        with open(path, "w") as tool_file:
            tool_file.write(GETENT)
        os.chmod(path, 0o755)
        os.environ["SCHOOL_GETENT"] = path

    def tearDown(self):
        os.environ.pop("SCHOOL_GETENT", None)
        super().tearDown()

    def state(self, sessions, **connections):
        state = super().state(sessions, **connections)
        state["sudo"] = ["administrator", "colleague"]
        state["uids"] = {"administrator": 1000, "colleague": 1005}
        return state


class PrivateWifi(Shared0015):

    def test_admin_alone_claims_for_itself_only(self):
        left = self.run_forget(self.state([["colleague", "user"]], home=[]))
        self.assertEqual(left["home"]["users"], ["colleague"])

    def test_private_network_kept_at_logout(self):
        state = self.state([], mine=["colleague"], student=[])
        self.assertEqual(list(self.run_forget(state, "--no-claim")), ["mine"])

    def test_private_network_not_shared_with_administrator(self):
        state = self.state([["administrator", "user"]], mine=["colleague"], free=[])
        left = self.run_forget(state)
        self.assertEqual(left["mine"]["users"], ["colleague"])
        self.assertEqual(left["free"]["users"], KEEPERS)

    def test_admin_with_someone_else_claims_nothing(self):
        for other in ("administrator", "tdsb-123456789"):
            state = self.state([["colleague", "user"], [other, "user"]], net=[])
            self.assertEqual(self.run_forget(state, "--claim-only")["net"]["users"], [])

    def test_not_in_sudo_any_more_forgets(self):
        state = self.state([], mine=["colleague"])
        state["sudo"] = ["administrator"]
        self.assertEqual(self.run_forget(state, "--no-claim"), {})

    def test_system_and_student_sudo_members_ignored(self):
        state = self.state([["tdsb-1", "user"]], net=[])
        state["sudo"] = ["administrator", "tdsb-1", "daemonish"]
        state["uids"].update({"tdsb-1": 1010, "daemonish": 120})
        self.assertEqual(self.run_forget(state, "--claim-only")["net"]["users"], [])
        state = self.state([["daemonish", "user"]], net=[])
        state["sudo"] = ["daemonish"]
        state["uids"]["daemonish"] = 120
        self.assertEqual(self.run_forget(state, "--claim-only")["net"]["users"], [])

    def test_two_private_admins_on_one_network_forgotten(self):
        state = self.state([], both=["colleague", "other"])
        state["sudo"].append("other")
        state["uids"]["other"] = 1006
        self.assertEqual(self.run_forget(state, "--no-claim"), {})

    def test_all_forgets_private_networks_too(self):
        state = self.state([["colleague", "user"]], mine=["colleague"])
        self.assertEqual(self.run_forget(state, "--all"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
