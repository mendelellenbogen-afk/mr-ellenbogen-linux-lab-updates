#!/usr/bin/env python3
"""Tests for 0023-targeted-messages: per-laptop message keys (reporter),
encrypted targeted messages (sender -> listener), laptop and student
filtering, and the targeting.sh update helpers. Earlier live-message rules
are rerun on the new listener. No network, no root.

    python3 -I update-repo/tests/test_0023_targeted_messages.py
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "updates", "0023-targeted-messages", "files", "usr", "local", "lib")
LISTENER = os.path.join(FILES, "lab-messages", "lab-messages-listener.py")
REPORTER = os.path.join(FILES, "lab-inventory", "lab-inventory-report")
TARGETING = os.path.join(FILES, "lab-updater", "targeting.sh")
SENDER = os.path.join(HERE, "..", "..", "tools", "send-message")

sys.path.insert(0, HERE)
import test_0008_live_messages as t8   # noqa: E402
import test_0019_admin_only_messages as t19   # noqa: E402
import test_0020_open_links as t20   # noqa: E402
import test_0021_fullscreen_links as t21   # noqa: E402
import test_0022_lab_inventory as t22   # noqa: E402

listener = t19.load("listener23", LISTENER)
for module in (t8, t19, t20, t21):
    module.listener = listener
t22.rep = t19.load("reporter23", REPORTER)


class Old0008(t8.LiveMessages):
    pass


class Old0019(t19.AdminOnly):
    pass


class Old0020(t20.OpenLinks):
    pass


class Old0021Routing(t21.Routing):
    pass


class Old0021Present(t21.LabPresent):
    pass


class Old0022Reporter(t22.Reporter):
    pass


class MessageKey(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = t22.rep.STATE_DIR
        t22.rep.STATE_DIR = self.dir

    def tearDown(self):
        t22.rep.STATE_DIR = self.saved
        shutil.rmtree(self.dir)

    def test_key_is_stable_private_and_remade_for_a_clone(self):
        first = t22.rep.message_key()
        self.assertEqual(t22.rep.message_key(), first)
        self.assertEqual(len(base64.b64decode(first)), 32)
        self.assertEqual(os.stat(os.path.join(self.dir, "message-key")).st_mode & 0o777, 0o600)
        with open(os.path.join(self.dir, "message-key.machine-id"), "w") as handle:
            handle.write("master-laptop")
        self.assertNotEqual(t22.rep.message_key(), first)


@unittest.skipUnless(os.path.exists(SENDER), "tools/send-message is only on the teacher's computer")
class Targeted(t19.AdminOnly):
    """Messages encrypted by the real sender, opened by the real listener."""

    def setUp(self):
        super().setUp()
        self.sender = t19.load("sender23", SENDER)
        self.sender.sign = self.sign_with_test_key
        self.keys = {}
        for name in ("lab-a", "lab-b", "lab-c"):
            state = os.path.join(self.dir, name)
            os.makedirs(state, exist_ok=True)
            saved = t22.rep.STATE_DIR
            t22.rep.STATE_DIR = state
            self.keys[name] = (t22.rep.message_key(), os.path.join(state, "message-key"))
            t22.rep.STATE_DIR = saved
        self.saved_host = (listener.HOSTNAME, listener.MESSAGE_KEY)

    def tearDown(self):
        listener.HOSTNAME, listener.MESSAGE_KEY = self.saved_host
        super().tearDown()

    def sign_with_test_key(self, text):
        path = os.path.join(self.dir, "signme")
        if os.path.exists(path + ".sig"):
            os.unlink(path + ".sig")
        with open(path, "w") as handle:
            handle.write(text)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", os.path.join(self.dir, "teacher"),
                        "-n", "lab-message", path], check=True)
        with open(path + ".sig") as handle:
            return handle.read()

    def envelope(self, targets, students=None, message_id="t1", tamper_targets=None):
        payload = {"v": 1, "id": message_id, "sent": t19.NOW, "title": "T", "text": "hi", "code": "",
                   "to_laptops": tamper_targets or targets}
        if students:
            payload["to_students"] = students
        text = json.dumps(payload)
        inner = json.dumps({"payload": text, "sig": self.sign_with_test_key(text)})
        return self.sender.encrypt_for({n: self.keys[n][0] for n in targets}, inner.encode())

    def receive_on(self, laptop, body):
        listener.HOSTNAME, listener.MESSAGE_KEY = laptop, self.keys[laptop][1]
        self.windows.clear()
        self.deliver(("target-topic", body))
        return list(self.windows)

    def deliver(self, *events):
        saved = listener.listen_once

        def listen_once(server, topics, admin_topic, since, seen, on_event_id, target_topic=""):
            return saved(server, topics, admin_topic, since, seen, on_event_id, "target-topic")
        listener.listen_once = listen_once
        try:
            return super().deliver(*events)
        finally:
            listener.listen_once = saved

    def test_target_laptops_show_it_others_cannot_open_it(self):
        body = self.envelope(["lab-a", "lab-b"])
        self.assertEqual(self.receive_on("lab-a", body), ["administrator", "studenttest1", "tdsb-123456789"])
        self.assertEqual(self.receive_on("lab-b", body), ["administrator", "studenttest1", "tdsb-123456789"])
        self.assertEqual(self.receive_on("lab-c", body), [])
        self.assertIsNone(listener.open_targeted(body))     # lab-c can't decrypt

    def test_student_only_sees_it_in_their_own_session(self):
        body = self.envelope(["lab-a"], students=["123456789"])
        self.assertEqual(self.receive_on("lab-a", body), ["tdsb-123456789"])

    def test_student_not_logged_in_nobody_sees_it(self):
        body = self.envelope(["lab-a"], students=["999999999"])
        self.assertEqual(self.receive_on("lab-a", body), [])

    def test_signed_target_list_wins_over_the_envelope(self):
        # Encrypted to lab-b, but the signed payload says lab-a only.
        body = self.envelope(["lab-b"], tamper_targets=["lab-a"])
        self.assertEqual(self.receive_on("lab-b", body), [])

    def test_unsigned_inner_message_rejected(self):
        inner = json.dumps({"payload": json.dumps({"v": 1, "id": "x", "sent": t19.NOW, "title": "T",
                                                   "to_laptops": ["lab-a"]}), "sig": "nope"})
        body = self.sender.encrypt_for({"lab-a": self.keys["lab-a"][0]}, inner.encode())
        self.assertEqual(self.receive_on("lab-a", body), [])

    def test_targeted_payload_on_the_class_topic_still_only_reaches_its_laptops(self):
        payload = {"v": 1, "id": "c1", "sent": t19.NOW, "title": "T", "text": "", "code": "",
                   "to_laptops": ["lab-a"]}
        text = json.dumps(payload)
        body = json.dumps({"payload": text, "sig": self.sign_with_test_key(text)})
        listener.HOSTNAME = "lab-c"
        self.windows.clear()
        self.deliver((t19.CLASS_TOPIC, body))
        self.assertEqual(self.windows, [])

    def test_garbage_on_the_target_topic(self):
        for body in ("", "{}", '{"lab_target": 1, "to": {"lab-a": "AAAA"}, "epk": "AA==", "nonce": "", "data": ""}'):
            listener.HOSTNAME, listener.MESSAGE_KEY = "lab-a", self.keys["lab-a"][1]
            self.assertIsNone(listener.open_targeted(body), body)

    def test_sender_resolves_students_to_their_laptops(self):
        inventory = {
            "S1": {"report": {"name": "lab-a", "message_pubkey": self.keys["lab-a"][0],
                              "students": [{"student_id": "123456789"}]}},
            "S2": {"report": {"name": "lab-b", "message_pubkey": self.keys["lab-b"][0],
                              "students": [{"student_id": "123456789"}, {"student_id": "555"}]}},
            "S3": {"report": {"name": "lab-c", "students": [{"student_id": "555"}]}},     # not on 0023 yet
        }
        path = os.path.join(self.dir, "inventory.json")
        with open(path, "w") as handle:
            json.dump(inventory, handle)
        self.sender.INVENTORY = path
        self.assertEqual(sorted(self.sender.resolve_targets([], ["123456789"])), ["lab-a", "lab-b"])
        self.assertEqual(sorted(self.sender.resolve_targets(["LAB-C", "lab-a"], [])), ["lab-a"])
        with self.assertRaises(SystemExit):
            self.sender.resolve_targets([], ["000"])
        with self.assertRaises(SystemExit):
            self.sender.resolve_targets(["lab-c"], [])


class TargetingHelpers(unittest.TestCase):

    def run_bash(self, script, hostname="lab-jq8fzm2", accounts=("tdsb-349681030",)):
        directory = tempfile.mkdtemp()
        try:
            with open(os.path.join(directory, "hostname"), "w") as handle:
                handle.write(f"#!/bin/bash\necho {hostname}\n")
            with open(os.path.join(directory, "getent"), "w") as handle:
                handle.write("#!/bin/bash\ncase \" " + " ".join(accounts) + " \" in *\" $2 \"*) echo \"$2:x\";; *) exit 2;; esac\n")
            for tool in ("hostname", "getent"):
                os.chmod(os.path.join(directory, tool), 0o755)
            full = f'say() {{ echo "SAY $*"; }}\nsource "{TARGETING}"\n{script}\necho END'
            return subprocess.run(["bash", "-c", full], capture_output=True, text=True,
                                  env=dict(os.environ, PATH=directory + ":" + os.environ["PATH"])).stdout
        finally:
            shutil.rmtree(directory)

    def test_only_on_laptops(self):
        self.assertIn("END", self.run_bash("only_on_laptops lab-x LAB-JQ8FZM2"))
        out = self.run_bash("only_on_laptops lab-x lab-y")
        self.assertIn("not for this laptop", out)
        self.assertNotIn("END", out)

    def test_student_accounts(self):
        out = self.run_bash("student_accounts 349681030 111 | tr '\\n' ' '", accounts=("tdsb-349681030",))
        self.assertIn("tdsb-349681030 END", out.replace("\n", " "))
        self.assertNotIn("tdsb-111", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
