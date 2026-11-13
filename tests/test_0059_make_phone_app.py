#!/usr/bin/env python3
"""Tests for 0059-make-phone-app: the "Make a Phone App" window's work (no window).
Temp folders only; no root. The build service is a fake on 127.0.0.1.

    python3 -I update-repo/tests/test_0059_make_phone_app.py
"""

import importlib.util
import json
import os
import socket
import stat
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0059-make-phone-app")
APP = os.path.join(UPDATE, "files", "usr", "local", "lib", "lab-phone-app", "make-phone-app.py")
CODE = "ABCD2345"


def load(home, config):
    os.environ["HOME"] = home
    os.environ["LAB_PHONEAPP_CONFIG"] = config
    spec = importlib.util.spec_from_file_location("make_phone_app", APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeService(BaseHTTPRequestHandler):
    uploads = []
    states = {}

    def log_message(self, *a):
        pass

    def reply(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if u.path != "/apps/upload":
            return self.reply(404, {"error": "Not found."})
        if q.get("code", [""])[0] != CODE:
            return self.reply(403, {"error": "Wrong class code."})
        FakeService.uploads.append({"query": q, "path": self.path, "body": body,
                                    "student": self.headers.get("X-Lab-Student"),
                                    "laptop": self.headers.get("X-Lab-Laptop")})
        self.reply(200, {"id": "job12345678", "url": "https://x/apps/a/job12345678", "state": "queued", "error": ""})

    def do_GET(self):
        if self.path == "/apps/a/job12345678.json":
            return self.reply(200, FakeService.states.get("job", {"state": "queued", "ahead": 2}))
        if self.path == "/apps/a/job12345678/qr.svg":
            return self.reply(200, b"<svg/>", "image/svg+xml")
        self.reply(404, {"error": "Not found."})


class MakePhoneAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), FakeService)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.config = os.path.join(self.tmp.name, "config")
        with open(self.config, "w") as fh:
            fh.write(f"# comment\nSERVER=http://127.0.0.1:{self.http.server_port}/apps/\n")
        self.fx = self.project("IdeaProjects/Inventory", {
            "pom.xml": "<artifactId>javafx-controls</artifactId>",
            "src/main/java/a/Main.java": "import javafx.application.Application;",
            "src/main/resources/data.csv": "x",
            "target/classes/a/Main.class": "junk", ".idea/workspace.xml": "junk", ".git/HEAD": "junk",
            "out/x.txt": "junk", "Inventory.iml": "junk"})
        self.plain = self.project("CS/Java/Hello", {"Hello.java": "class Hello {}"})
        self.project("IdeaProjects/Empty", {"notes.txt": "no java"})
        FakeService.uploads.clear()
        FakeService.states.clear()
        self.m = load(self.home, self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, relative, files):
        root = os.path.join(self.home, relative)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)
        return root

    def test_projects_javafx_first_and_only_java(self):
        found = self.m.find_projects(self.home)
        self.assertEqual([(p, fx) for p, fx, _ in found], [(self.fx, True), (self.plain, False)])

    def test_zip_leaves_out_build_output_and_ide_files(self):
        dest = os.path.join(self.tmp.name, "p.zip")
        self.m.make_zip(self.fx, dest)
        names = sorted(zipfile.ZipFile(dest).namelist())
        self.assertEqual(names, ["Inventory/pom.xml", "Inventory/src/main/java/a/Main.java",
                                 "Inventory/src/main/resources/data.csv"])

    def test_too_big_project_is_refused(self):
        self.m.MAX_ZIP = 10
        with self.assertRaises(self.m.StudentError) as caught:
            self.m.make_zip(self.fx, os.path.join(self.tmp.name, "p.zip"))
        self.assertIn("too big", str(caught.exception))

    def test_send_puts_who_in_headers_not_the_address_and_remembers_the_code(self):
        self.m.student_number = lambda: "349999999"
        answer = self.m.send(self.fx, "My Inventory", " abcd-2345 ")
        self.assertEqual(answer["id"], "job12345678")
        up = FakeService.uploads[0]
        self.assertEqual((up["student"], up["laptop"]), ("349999999", socket.gethostname()))
        self.assertNotIn("349999999", up["path"])
        self.assertEqual(up["query"]["name"], ["My Inventory"])
        self.assertIn("Inventory/src/main/java/a/Main.java",
                      zipfile.ZipFile(__import__("io").BytesIO(up["body"])).namelist())
        self.assertEqual(self.m.read_code(), CODE)
        self.assertEqual(stat.S_IMODE(os.stat(self.m.CODE_FILE).st_mode), 0o600)

    def test_wrong_code_is_a_student_message_and_not_remembered(self):
        with self.assertRaises(self.m.StudentError) as caught:
            self.m.send(self.fx, "App", "WRONG123")
        self.assertIn("Wrong class code", str(caught.exception))
        self.assertEqual(self.m.read_code(), "")
        with self.assertRaises(self.m.StudentError):
            self.m.send(self.fx, "App", "  ")

    def test_status_qr_and_wait_text(self):
        self.assertEqual(self.m.job_status("job12345678")["ahead"], 2)
        self.assertEqual(self.m.qr_picture("job12345678"), b"<svg/>")
        self.assertIn("2 projects ahead", self.m.wait_text({"state": "queued", "ahead": 2}))
        self.assertIn("next in line", self.m.wait_text({"state": "queued", "ahead": 0}))
        self.assertIn("being built", self.m.wait_text({"state": "building"}))

    def test_service_down_or_no_config(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with open(self.config, "w") as fh:
            fh.write(f"SERVER=http://127.0.0.1:{port}/apps\n")
        with self.assertRaises(self.m.StudentError) as caught:
            self.m.job_status("job12345678")
        self.assertIn("Wi-Fi", str(caught.exception))
        os.remove(self.config)
        with self.assertRaises(self.m.StudentError) as caught:
            self.m.server()
        self.assertIn("Ask your teacher", str(caught.exception))

    def test_student_number(self):
        self.m.getpass.getuser = lambda: "tdsb-349999999"
        self.assertEqual(self.m.student_number(), "349999999")
        self.m.getpass.getuser = lambda: "studenttest1"
        self.assertEqual(self.m.student_number(), "studenttest1")

    def test_install_files_match(self):
        with open(os.path.join(UPDATE, "install.sh")) as fh:
            install = fh.read()
        for src in ["files/etc/lab-phone-app/config", "files/usr/local/lib/lab-phone-app/make-phone-app.py",
                    "files/usr/local/share/applications/lab-make-phone-app.desktop"]:
            self.assertTrue(os.path.isfile(os.path.join(UPDATE, src)), src)
            self.assertIn(src, install)
        with open(os.path.join(UPDATE, "files/usr/local/share/applications/lab-make-phone-app.desktop")) as fh:
            self.assertIn("Exec=/usr/bin/python3 /usr/local/lib/lab-phone-app/make-phone-app.py", fh.read())
        with open(os.path.join(UPDATE, "files/etc/lab-phone-app/config")) as fh:
            self.assertRegex(fh.read(), r"(?m)^SERVER=https://\S+\.ts\.net/apps$")


if __name__ == "__main__":
    unittest.main(verbosity=1)
