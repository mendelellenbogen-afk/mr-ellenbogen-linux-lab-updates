#!/usr/bin/env python3
"""Tests for 0029-taken-home: the reporter's Wi-Fi kind (school/other/none),
location lookup once per visit, no home network name in the report, and,
when run on the teacher's computer, the collector's Wi-Fi visits and the
Taken home list. Made-up IDs and places; no network, no root.

    python3 -I update-repo/tests/test_0029_taken_home.py
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import pwd
import shutil
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0029-taken-home")
REPORTER = os.path.join(UPDATE, "files", "usr", "local", "lib", "lab-inventory", "lab-inventory-report")
COLLECTOR = os.path.join(HERE, "..", "..", "tools", "lab-inventory-collector")

SCHOOL = (43.7697, -79.4064)
FAR_AWAY = {"lat": 43.6500, "lon": -79.3800, "accuracy_m": 40, "source": "wifi", "found_at": "x"}   # ~13 km


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


rep = load("reporter29", REPORTER)


def account(name, uid):
    return pwd.struct_passwd((name, "x", uid, uid, "", f"/home/{name}", "/bin/bash"))


ACCOUNTS = [account("administrator", 1000), account("tdsb-123456789", 1001)]


class FakeNetwork:
    """Stands in for nmcli: the connected SSID and the access points around."""

    def __init__(self):
        self.ssid = "TDSB-WIFI"
        self.points = [("AA:BB:CC:00:00:01", 80), ("AA:BB:CC:00:00:02", 40)]
        self.scans = 0

    def run(self, command):
        if command[:2] != [rep.NMCLI, "-t"]:
            return ""
        if "ACTIVE,SSID" in command:
            if self.ssid is None:
                return "no:Neighbour\n"
            return f"no:Neighbour\nyes:{self.ssid.replace(':', chr(92) + ':')}\n"
        if "BSSID,SIGNAL" in command:
            self.scans += 1
            return "".join(f"{b.replace(':', chr(92) + ':')}:{s}\n" for b, s in self.points)
        return ""


class Reporter(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = (rep.STATE_DIR, rep.sessions, rep.pwd.getpwall, rep.build_report, rep.send,
                      rep.read_config, rep.TEACHER_KEY, rep.run, rep.locate, rep.CONFIG_FILE)
        rep.STATE_DIR = os.path.join(self.dir, "state")
        rep.pwd.getpwall = lambda: ACCOUNTS
        self.teacher = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rep.TEACHER_KEY = os.path.join(self.dir, "teacher.pub.pem")
        with open(rep.TEACHER_KEY, "wb") as handle:
            handle.write(self.teacher.public_key().public_bytes(serialization.Encoding.PEM,
                                                                serialization.PublicFormat.SubjectPublicKeyInfo))
        self.sent = []
        rep.send = lambda server, topic, body: self.sent.append(body)
        rep.read_config = lambda: ("https://ntfy.example", "topic")
        rep.build_report = lambda times: {"v": 1, "name": "lab-sn1", "serial": "SN1", "machine_id": "m1",
                                          "students": [], "other_accounts": []}
        self.net = FakeNetwork()
        rep.run = self.net.run
        self.lookups = []
        self.answer = FAR_AWAY

        def fake_locate():
            self.lookups.append(1)
            return dict(self.answer) if self.answer else None
        rep.locate = fake_locate
        rep.sessions = lambda: [("tdsb-123456789", 1_800_000_000)]

    def tearDown(self):
        (rep.STATE_DIR, rep.sessions, rep.pwd.getpwall, rep.build_report, rep.send,
         rep.read_config, rep.TEACHER_KEY, rep.run, rep.locate, rep.CONFIG_FILE) = self.saved
        shutil.rmtree(self.dir)

    def last_report(self):
        outer = json.loads(self.sent[-1])
        import base64, zlib
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = lambda k: base64.b64decode(outer[k])
        secret = self.teacher.decrypt(raw("key"), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                               algorithm=hashes.SHA256(), label=None))
        envelope = json.loads(zlib.decompress(AESGCM(secret).decrypt(raw("nonce"), raw("data"), None)))
        return json.loads(envelope["report"]), envelope["report"]

    def test_terse_output_with_escaped_colons(self):
        self.assertEqual(rep.terse("yes:My\\:Net\nAA\\:BB:70"), [["yes", "My:Net"], ["AA:BB", "70"]])

    def test_school_wifi_no_location_lookup(self):
        rep.main()
        report, _text = self.last_report()
        self.assertEqual(report["network"]["wifi"], "school")
        self.assertNotIn("location", report["network"])
        self.assertEqual(report["logged_in"], ["tdsb-123456789"])
        self.assertEqual(self.lookups, [])

    def test_home_wifi_located_once_and_name_never_sent(self):
        self.net.ssid = "Smith Family: 5G"
        rep.main()
        report, text = self.last_report()
        self.assertEqual(report["network"]["wifi"], "other")
        self.assertEqual(report["network"]["location"]["lat"], FAR_AWAY["lat"])
        self.assertNotIn("Smith", text)
        self.assertNotIn("Smith", json.dumps(rep.load_state()))
        rep.main()                                  # same network: no new lookup, nothing new to send
        self.assertEqual(len(self.lookups), 1)
        self.assertEqual(len(self.sent), 1)

    def test_failed_lookup_retried_after_30_minutes_only(self):
        self.net.ssid = "Home"
        self.answer = None
        rep.main()
        rep.main()
        self.assertEqual(len(self.lookups), 1)
        state = rep.load_state()
        state["network"]["location_tried"] -= 31 * 60
        rep.save_state(state)
        self.answer = FAR_AWAY
        rep.main()
        self.assertEqual(len(self.lookups), 2)
        self.assertIn("location", self.last_report()[0]["network"])

    def test_change_of_wifi_is_reported_and_new_visit_after_6_hours(self):
        rep.main()
        self.net.ssid = "Home"
        rep.main()
        self.assertEqual(len(self.sent), 2)
        first_since = rep.load_state()["network"]["since"]
        state = rep.load_state()
        state["network"]["seen"] -= 7 * 3600          # e.g. the next day on the same home Wi-Fi
        state["network"]["since"] -= 7 * 3600
        rep.save_state(state)
        rep.main()
        self.assertGreater(rep.load_state()["network"]["since"], first_since - 7 * 3600)
        self.assertEqual(len(self.lookups), 2)        # new visit: located again

    def test_no_wifi(self):
        self.net.ssid = None
        self.assertEqual(rep.network({}, 1_800_000_000), {"wifi": "none"})

    def test_locate_sends_access_points_and_marks_ip_guesses(self):
        rep.locate = self.saved[8]
        rep.CONFIG_FILE = os.path.join(self.dir, "config")
        with open(rep.CONFIG_FILE, "w") as handle:
            handle.write("SERVER=x\nTOPIC=y\nLOCATION_URL=https://locate.example/v1/geolocate\n")
        asked = []

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout):
            asked.append(json.loads(request.data))
            return Answer(json.dumps(self.reply).encode())
        saved_urlopen = rep.urllib.request.urlopen
        rep.urllib.request.urlopen = fake_urlopen
        try:
            self.reply = {"location": {"lat": 43.123456789, "lng": -79.5}, "accuracy": 35.4}
            found = rep.locate()
            self.assertEqual((found["lat"], found["source"], found["accuracy_m"]), (43.12346, "wifi", 35))
            self.assertEqual(asked[0]["wifiAccessPoints"][0], {"macAddress": "aa:bb:cc:00:00:01",
                                                               "signalStrength": -60})
            self.reply = {"location": {"lat": 43.7, "lng": -79.4}, "accuracy": 25000, "fallback": "ipf"}
            self.assertEqual(rep.locate()["source"], "ip")
            self.reply = {"error": {"code": 404}}
            self.assertIsNone(rep.locate())
            with open(rep.CONFIG_FILE, "w") as handle:
                handle.write("SERVER=x\nTOPIC=y\nLOCATION_URL=\n")
            self.assertIsNone(rep.locate())
            self.assertEqual(len(asked), 3)
        finally:
            rep.urllib.request.urlopen = saved_urlopen

    def test_dispatcher_and_install(self):
        with open(os.path.join(UPDATE, "files", "etc", "NetworkManager", "dispatcher.d", "91-lab-inventory")) as h:
            text = h.read()
        self.assertIn("systemctl start --no-block lab-inventory.service", text)
        with open(os.path.join(UPDATE, "install.sh")) as h:
            install = h.read()
        for path in ("/usr/local/lib/lab-inventory/lab-inventory-report", "/etc/lab-inventory/config",
                     "/etc/NetworkManager/dispatcher.d/91-lab-inventory"):
            self.assertIn(path, install)


@unittest.skipUnless(os.path.exists(COLLECTOR), "the collector is only on the teacher's computer")
class Collector(Reporter):

    def setUp(self):
        super().setUp()
        self.col = load("collector29", COLLECTOR)
        self.col.DATA_DIR = os.path.join(self.dir, "data")
        self.col.UPDATES_DIR = os.path.join(self.dir, "updates")
        os.makedirs(self.col.UPDATES_DIR)
        self.sheet = []
        self.col.sync_sheet = lambda laptops, students, taken=None: self.sheet.append(taken)
        self.clock = 1_800_000_000

    def deliver(self):
        self.clock += 600
        envelope = self.col.decrypt(self.sent[-1], self.teacher)
        return self.col.store(envelope, self.clock)

    def test_school_home_school_is_back_at_school(self):
        rep.main()
        self.deliver()
        self.assertEqual(self.col.load("visits.json", {})["SN1"][0]["wifi"], "school")
        self.assertEqual(self.sheet[-1], [])
        self.net.ssid = "Home"
        rep.main()
        self.assertIn("Wi-Fi: other", self.deliver())
        row = self.sheet[-1][0]
        self.assertEqual((row["laptop"], row["status"], row["who_off_site"], row["off_site_visits"]),
                         ("lab-sn1", "Off-site", "123456789", 1))
        self.assertIn("13.", row["distance_from_school"])
        self.net.ssid = "TDSB-WIFI"
        rep.main()
        self.deliver()
        self.assertEqual(self.sheet[-1][0]["status"], "Back at school")
        with open(os.path.join(self.col.DATA_DIR, "taken-home.csv")) as handle:
            self.assertIn("Back at school", handle.read())

    def test_hotspot_at_school_is_not_off_site(self):
        self.net.ssid = "Phone hotspot"
        self.answer = {"lat": SCHOOL[0] + 0.001, "lon": SCHOOL[1], "accuracy_m": 30, "source": "wifi",
                       "found_at": "x"}
        rep.main()
        self.deliver()
        self.assertEqual(self.sheet[-1], [])

    def test_ip_guess_counts_as_off_site_without_a_distance(self):
        self.net.ssid = "Home"
        self.answer = {"lat": SCHOOL[0], "lon": SCHOOL[1], "accuracy_m": 25000, "source": "ip", "found_at": "x"}
        rep.main()
        self.deliver()
        self.assertEqual(self.sheet[-1][0]["distance_from_school"], "city only (from internet address)")

    def test_no_coordinates_in_the_sheet_table(self):
        self.net.ssid = "Home"
        rep.main()
        self.deliver()
        text = json.dumps(self.sheet[-1])
        self.assertNotIn(str(FAR_AWAY["lat"]), text)
        self.assertNotIn(str(FAR_AWAY["lon"]), text)

    def test_old_reports_without_network_are_fine(self):
        saved_network = rep.network
        rep.network = lambda state, now: None
        try:
            rep.main()
            envelope = self.col.decrypt(self.sent[-1], self.teacher)
            report = json.loads(envelope["report"])
            self.assertIsNone(report["network"])
            self.assertIn("lab-sn1", self.col.store(envelope, self.clock))
            self.assertEqual(self.col.load("visits.json", {}), {})
        finally:
            rep.network = saved_network


if __name__ == "__main__":
    unittest.main(verbosity=2)
