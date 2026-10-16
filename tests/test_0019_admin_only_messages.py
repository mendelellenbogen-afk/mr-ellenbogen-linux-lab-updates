#!/usr/bin/env python3
"""Tests for 0019-admin-only-messages: the 0008 rules still hold, and admin-only
messages reach only sudo-group sessions. Throwaway SSH keys; no network, no root.

    python3 -I update-repo/tests/test_0019_admin_only_messages.py
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0019-admin-only-messages", "files")
LISTENER = os.path.join(UPDATE, "usr", "local", "lib", "lab-messages", "lab-messages-listener.py")
CONFIG = os.path.join(UPDATE, "etc", "lab-messages", "config")
SENDER = os.path.join(HERE, "..", "..", "tools", "send-message")


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


listener = load("listener19", LISTENER)

# The 0008 tests, run against the new listener.
sys.path.insert(0, HERE)
import test_0008_live_messages as old_tests  # noqa: E402
old_tests.listener = listener


class Old0008Rules(old_tests.LiveMessages):
    pass


NOW = 1_800_000_000
ADMIN_TOPIC = "admins-topic"
CLASS_TOPIC = "class-topic"


class AdminOnly(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "teacher",
                        "-f", os.path.join(cls.dir, "teacher")], check=True)
        cls.signers = os.path.join(cls.dir, "allowed_signers")
        with open(os.path.join(cls.dir, "teacher.pub")) as public_key, open(cls.signers, "w") as signers:
            signers.write("teacher@lab " + public_key.read())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def setUp(self):
        self.saved = {name: getattr(listener, name) for name in
                      ("ALLOWED_SIGNERS", "RUN_DIR", "logged_in_users", "is_admin", "subprocess", "time")}
        listener.ALLOWED_SIGNERS = self.signers
        listener.RUN_DIR = os.path.join(self.dir, "run")
        listener.logged_in_users = lambda: ["administrator", "studenttest1", "tdsb-123456789"]
        listener.is_admin = lambda user: user == "administrator"
        self.windows = []
        test = self

        class FakeSubprocess:
            @staticmethod
            def run(args, **kwargs):
                if args[0] == "/usr/bin/systemd-run":
                    machine = next(a for a in args if a.startswith("--machine="))
                    test.windows.append(machine.split("=")[1].rstrip("@"))
                    return subprocess.CompletedProcess(args, 0, "", "")
                return subprocess.run(args, **kwargs)   # ssh-keygen verify

        listener.subprocess = FakeSubprocess
        real_exists = os.path.exists
        self.saved_exists = os.path.exists
        os.path.exists = lambda path: True if path.startswith("/run/user/") else real_exists(path)
        listener.pwd = type("P", (), {"getpwnam": staticmethod(lambda u: type("E", (), {"pw_uid": 1000})())})

        class FakeTime:
            @staticmethod
            def time():
                return NOW + 5
        listener.time = FakeTime

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(listener, name, value)
        os.path.exists = self.saved_exists
        import pwd
        listener.pwd = pwd

    def body(self, message_id, to=None):
        payload = {"v": 1, "id": message_id, "sent": NOW, "title": "T", "text": "hi", "code": ""}
        if to:
            payload["to"] = to
        payload_text = json.dumps(payload)
        path = os.path.join(self.dir, message_id)
        with open(path, "w") as payload_file:
            payload_file.write(payload_text)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", os.path.join(self.dir, "teacher"),
                        "-n", "lab-message", path], check=True)
        with open(path + ".sig") as sig_file:
            return json.dumps({"payload": payload_text, "sig": sig_file.read()})

    def deliver(self, *events):
        lines = [json.dumps({"event": "open"}).encode()] + [
            json.dumps({"event": "message", "id": f"e{i}", "time": NOW, "topic": topic,
                        "message": body}).encode() for i, (topic, body) in enumerate(events)]
        urls = []

        class Stream(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout):
            urls.append(request.full_url)
            return Stream(b"\n".join(lines) + b"\n")

        saved = listener.urllib.request.urlopen
        listener.urllib.request.urlopen = fake_urlopen
        try:
            listener.listen_once("https://ntfy.example", [CLASS_TOPIC, ADMIN_TOPIC], ADMIN_TOPIC,
                                 None, set(), lambda t: None)
        finally:
            listener.urllib.request.urlopen = saved
        return urls

    def test_class_message_reaches_everyone(self):
        self.deliver((CLASS_TOPIC, self.body("m1")))
        self.assertEqual(self.windows, ["administrator", "studenttest1", "tdsb-123456789"])

    def test_admin_message_reaches_only_admins(self):
        self.deliver((ADMIN_TOPIC, self.body("m2", to="admins")))
        self.assertEqual(self.windows, ["administrator"])

    def test_admin_payload_reposted_to_class_topic_stays_admin_only(self):
        self.deliver((CLASS_TOPIC, self.body("m3", to="admins")))
        self.assertEqual(self.windows, ["administrator"])

    def test_anything_on_admin_topic_is_admin_only(self):
        self.deliver((ADMIN_TOPIC, self.body("m4")))
        self.assertEqual(self.windows, ["administrator"])

    def test_subscribes_to_both_topics_in_one_connection(self):
        urls = self.deliver()
        self.assertEqual(urls, [f"https://ntfy.example/{CLASS_TOPIC},{ADMIN_TOPIC}/json"])

    def test_no_admin_logged_in_shows_nothing(self):
        listener.logged_in_users = lambda: ["tdsb-123456789"]
        self.deliver((ADMIN_TOPIC, self.body("m5", to="admins")))
        self.assertEqual(self.windows, [])


class Config(unittest.TestCase):

    @unittest.skipUnless(os.path.exists(SENDER), "tools/send-message is only on the teacher's computer")
    def test_config_has_both_topics_and_matches_the_sender(self):
        listener.CONFIG_FILE = CONFIG
        server, topic, admin_topic = listener.read_config()
        self.assertEqual(server, "https://ntfy.sh")
        sender = load("sender", SENDER)
        self.assertEqual(topic, sender.TOPIC)
        self.assertEqual(admin_topic, sender.ADMIN_TOPIC)
        self.assertNotEqual(topic, admin_topic)

    def test_old_config_without_admin_topic_still_works(self):
        path = os.path.join(tempfile.mkdtemp(), "config")
        with open(path, "w") as config:
            config.write("SERVER=https://ntfy.sh/\nTOPIC=t\n")
        listener.CONFIG_FILE = path
        self.assertEqual(listener.read_config(), ("https://ntfy.sh", "t", ""))
        shutil.rmtree(os.path.dirname(path))

    def test_is_admin_uses_the_sudo_group(self):
        import grp
        sudo = grp.getgrnam("sudo")
        for member in sudo.gr_mem:
            self.assertTrue(listener.is_admin(member))
        self.assertFalse(listener.is_admin("no-such-user-xyz"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
