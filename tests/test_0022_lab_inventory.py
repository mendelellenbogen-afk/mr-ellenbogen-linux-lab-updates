#!/usr/bin/env python3
"""Tests for 0022-lab-inventory: the laptop reporter (accounts, login times,
change detection, per-machine key) and, when run on the teacher's computer,
the collector (decrypt, signature, fakes, re-imaging, one entry per laptop,
flags). Throwaway keys; no network, no root.

    python3 -I update-repo/tests/test_0022_lab_inventory.py
"""

import importlib.machinery
import importlib.util
import json
import os
import pwd
import shutil
import tempfile
import time
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTER = os.path.join(HERE, "..", "updates", "0022-lab-inventory", "files",
                        "usr", "local", "lib", "lab-inventory", "lab-inventory-report")
COLLECTOR = os.path.join(HERE, "..", "..", "tools", "lab-inventory-collector")


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


rep = load("reporter22", REPORTER)


def account(name, uid, home=None):
    return pwd.struct_passwd((name, "x", uid, uid, "", home or f"/home/{name}", "/bin/bash"))


ACCOUNTS = [account("root", 0, "/root"), account("administrator", 1000), account("studenttest1", 1001),
            account("tdsb-349681030", 1002), account("tdsb-111222333", 1003), account("nobody", 65534, "/nonexistent")]


class Reporter(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = (rep.STATE_DIR, rep.sessions, rep.pwd.getpwall, rep.build_report, rep.send, rep.read_config,
                      rep.TEACHER_KEY)
        rep.STATE_DIR = os.path.join(self.dir, "state")
        rep.pwd.getpwall = lambda: ACCOUNTS
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rep.TEACHER_KEY = os.path.join(self.dir, "teacher.pub.pem")
        with open(rep.TEACHER_KEY, "wb") as handle:
            handle.write(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo))
        self.teacher = key
        self.sent = []
        rep.send = lambda server, topic, body: self.sent.append(body)
        rep.read_config = lambda: ("https://ntfy.example", "topic")
        real_build = self.saved[3]
        rep.build_report = lambda times: dict(real_build(times), serial="SN1", name="lab-sn1")

    def tearDown(self):
        (rep.STATE_DIR, rep.sessions, rep.pwd.getpwall, rep.build_report, rep.send, rep.read_config,
         rep.TEACHER_KEY) = self.saved
        shutil.rmtree(self.dir)

    def test_students_and_other_accounts(self):
        students, others = rep.accounts({"tdsb-349681030": 1_800_000_000})
        self.assertEqual([s["student_id"] for s in students], ["111222333", "349681030"])
        self.assertEqual(students[1]["last_login"], time.strftime("%Y-%m-%d %H:%M", time.localtime(1_800_000_000)))
        self.assertEqual(students[0]["last_login"], "")
        self.assertEqual([o["account"] for o in others], ["administrator", "studenttest1"])

    def test_nobody_logged_in_sends_nothing(self):
        rep.sessions = lambda: []
        rep.main()
        self.assertEqual(self.sent, [])

    def test_sends_once_then_only_on_change(self):
        rep.sessions = lambda: [("tdsb-349681030", 1_800_000_000)]
        rep.main()
        rep.main()
        self.assertEqual(len(self.sent), 1)
        rep.sessions = lambda: [("tdsb-349681030", 1_800_000_500)]     # a new login
        rep.main()
        self.assertEqual(len(self.sent), 2)

    def test_resends_after_a_day(self):
        rep.sessions = lambda: [("administrator", 1_800_000_000)]
        rep.main()
        state = rep.load_state()
        state["sent_at"] -= 25 * 3600
        rep.save_state(state)
        rep.main()
        self.assertEqual(len(self.sent), 2)

    def test_login_time_kept_after_logout_and_forgotten_when_account_deleted(self):
        rep.sessions = lambda: [("tdsb-111222333", 1_800_000_000)]
        rep.main()
        rep.sessions = lambda: [("administrator", 1_800_000_100)]
        rep.main()
        self.assertIn("tdsb-111222333", rep.load_state()["last_login"])
        rep.pwd.getpwall = lambda: [a for a in ACCOUNTS if a.pw_name != "tdsb-111222333"]
        rep.main()
        self.assertNotIn("tdsb-111222333", rep.load_state()["last_login"])

    def test_new_machine_id_makes_a_new_laptop_key(self):
        key, first = rep.laptop_key()
        with open(os.path.join(rep.STATE_DIR, "laptop-key.machine-id"), "w") as handle:
            handle.write("the-master-laptop")     # as if cloned from the master image
        key, second = rep.laptop_key()
        self.assertNotEqual(first, second)
        self.assertEqual(rep.laptop_key()[1], second)

    def test_free_space_alone_does_not_trigger_a_report(self):
        report = {"a": 1, "root_free_gb": 50}
        self.assertEqual(rep.stable_hash(report), rep.stable_hash(dict(report, root_free_gb=49)))
        self.assertNotEqual(rep.stable_hash(report), rep.stable_hash(dict(report, a=2)))


@unittest.skipUnless(os.path.exists(COLLECTOR), "the collector is only on the teacher's computer")
class Collector(Reporter):

    def setUp(self):
        super().setUp()
        self.col = load("collector22", COLLECTOR)
        self.col.DATA_DIR = os.path.join(self.dir, "data")
        self.col.UPDATES_DIR = os.path.join(self.dir, "updates")
        os.makedirs(os.path.join(self.col.UPDATES_DIR, "0022-lab-inventory"))
        rep.sessions = lambda: [("tdsb-349681030", 1_800_000_000)]

    def receive(self, body, at=1_800_000_100):
        return self.col.store(self.col.decrypt(body, self.teacher), at)

    def inventory(self):
        return self.col.load("inventory.json", {})

    def test_report_is_decrypted_verified_and_stored(self):
        rep.main()
        self.assertIn("2 student account", self.receive(self.sent[-1]))
        entry = self.inventory()["SN1"]
        self.assertEqual([s["student_id"] for s in entry["report"]["students"]], ["111222333", "349681030"])
        with open(os.path.join(self.col.DATA_DIR, "students.csv")) as handle:
            self.assertIn("349681030,lab-sn1,SN1", handle.read())

    def test_new_report_replaces_the_old_student_list(self):
        rep.main()
        self.receive(self.sent[-1])
        rep.pwd.getpwall = lambda: [a for a in ACCOUNTS if a.pw_name != "tdsb-349681030"]
        rep.sessions = lambda: [("tdsb-111222333", 1_800_000_900)]
        rep.main()
        self.receive(self.sent[-1], at=1_800_001_000)
        inventory = self.inventory()
        self.assertEqual(len(inventory), 1)
        self.assertEqual([s["student_id"] for s in inventory["SN1"]["report"]["students"]], ["111222333"])
        self.assertEqual(inventory["SN1"]["first_seen"], 1_800_000_100)

    def test_tampered_report_rejected(self):
        rep.main()
        envelope = self.col.decrypt(self.sent[-1], self.teacher)
        envelope["report"] = envelope["report"].replace("349681030", "999999999")
        self.assertIn("bad signature", self.col.store(envelope, 1))
        self.assertEqual(self.inventory(), {})

    def test_other_key_same_machine_is_rejected_new_machine_is_flagged(self):
        rep.main()
        self.receive(self.sent[-1])
        shutil.rmtree(rep.STATE_DIR)                         # same machine-id, new key: a fake
        rep.main()
        self.assertIn("possible fake", self.receive(self.sent[-1]))
        real_build = rep.build_report
        rep.build_report = lambda times: dict(real_build(times), machine_id="re-imaged")
        shutil.rmtree(rep.STATE_DIR)
        rep.main()
        self.receive(self.sent[-1])
        self.assertTrue(any("re-imaged" in n for n in self.inventory()["SN1"]["notes"]))

    def test_flags(self):
        now = 1_800_000_000
        entry = {"last_seen": now - 40 * 86400, "notes": [], "report": {
            "serial": "", "pci": {"storage_raid": True}, "battery": [{"health_percent": 41}],
            "root_free_gb": 9, "ram_gb": 4.0, "lab_updates": {"latest": "0019-admin-only-messages"}}}
        text = "; ".join(self.col.flags(entry, 22, now))
        for expected in ("RAID", "battery worn (41%)", "low disk (9 GB", "low RAM (4.0 GB)",
                         "behind on lab updates (0019)", "not seen for 40 days", "serial number unreadable"):
            self.assertIn(expected, text)
        healthy = {"last_seen": now, "notes": [], "report": {
            "serial": "SN", "pci": {}, "battery": [{"health_percent": 90}], "root_free_gb": 100,
            "ram_gb": 16, "lab_updates": {"latest": "0022-lab-inventory"}}}
        self.assertEqual(self.col.flags(healthy, 22, now), [])

    def test_garbage_rejected(self):
        for body in ("", "{}", '{"lab_inventory": 1, "key": "AA==", "nonce": "AA==", "data": "AA=="}'):
            with self.assertRaises(Exception):
                self.col.decrypt(body, self.teacher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
