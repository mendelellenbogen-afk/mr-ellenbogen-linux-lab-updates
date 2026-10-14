#!/usr/bin/env python3
"""Offline tests for 0008-live-messages: signature, freshness and replay rules.
Uses throwaway SSH keys; no network, no root.

    python3 -I update-repo/tests/test_0008_live_messages.py
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LISTENER = os.path.join(HERE, "..", "updates", "0008-live-messages", "files",
                        "usr", "local", "lib", "lab-messages", "lab-messages-listener.py")

loader = importlib.machinery.SourceFileLoader("listener", LISTENER)
spec = importlib.util.spec_from_loader("listener", loader)
listener = importlib.util.module_from_spec(spec)
loader.exec_module(listener)

NOW = 1_800_000_000


class LiveMessages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        for name in ("teacher", "stranger"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name,
                            "-f", os.path.join(cls.dir, name)], check=True)
        with open(os.path.join(cls.dir, "teacher.pub")) as public_key:
            cls.signers = os.path.join(cls.dir, "allowed_signers")
            with open(cls.signers, "w") as signers:
                signers.write("teacher@lab " + public_key.read())
        listener.ALLOWED_SIGNERS = cls.signers

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def body(self, sent=NOW, message_id="m1", key="teacher", namespace="lab-message", tamper=False):
        payload = json.dumps({"v": 1, "id": message_id, "sent": sent, "title": "T", "text": "", "code": "x = 1"})
        path = os.path.join(self.dir, "payload")
        if os.path.exists(path + ".sig"):
            os.unlink(path + ".sig")
        with open(path, "w") as payload_file:
            payload_file.write(payload)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", os.path.join(self.dir, key),
                        "-n", namespace, path], check=True)
        with open(path + ".sig") as sig_file:
            signature = sig_file.read()
        if tamper:
            payload = payload.replace('"x = 1"', '"import os; os.system(1)"')
        return json.dumps({"payload": payload, "sig": signature})

    def test_fresh_signed_message_is_shown(self):
        message = listener.parse(self.body(), set(), now=NOW + 5)
        self.assertEqual(message["code"], "x = 1")

    def test_message_older_than_two_minutes_is_never_shown(self):
        self.assertIsNone(listener.parse(self.body(sent=NOW - 121), set(), now=NOW))
        self.assertIsNotNone(listener.parse(self.body(sent=NOW - 119, message_id="m2"), set(), now=NOW))

    def test_message_from_the_future_rejected(self):
        self.assertIsNone(listener.parse(self.body(sent=NOW + 3600), set(), now=NOW))

    def test_same_message_shown_once(self):
        seen = set()
        self.assertIsNotNone(listener.parse(self.body(), seen, now=NOW))
        self.assertIsNone(listener.parse(self.body(), seen, now=NOW + 1))

    def test_wrong_key_rejected(self):
        self.assertIsNone(listener.parse(self.body(key="stranger"), set(), now=NOW))

    def test_update_signature_cannot_be_reused_as_a_message(self):
        self.assertIsNone(listener.parse(self.body(namespace="git"), set(), now=NOW))

    def test_tampered_payload_rejected(self):
        self.assertIsNone(listener.parse(self.body(tamper=True), set(), now=NOW))

    def test_garbage_rejected(self):
        for body in ("", "hello", "{}", '{"payload": 1}', json.dumps({"payload": "{}", "sig": "x"})):
            self.assertIsNone(listener.parse(body, set(), now=NOW), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
