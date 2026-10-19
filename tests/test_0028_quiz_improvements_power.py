#!/usr/bin/env python3
"""Tests for 0028-quiz-improvements-power: the quiz agent and window as changed
by 0028 (first/last name + student ID + Edit name, HAND IN + countdown, starter
program + Reset code), the 0027 behaviour they keep, and the power settings.
Temp folders and fake commands only: no root, no network, no real firewall,
USB or apps are touched. The window runs on a private Broadway display when
gtk4-broadwayd is installed. Uses a small made-up quiz (this repo is public).

    python3 -I update-repo/tests/test_0028_quiz_improvements_power.py
"""

import base64
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zlib
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0028-quiz-improvements-power")
LIB = os.path.join(UPDATE, "files", "usr", "local", "lib", "lab-quiz")
AGENT = os.path.join(LIB, "lab-quiz-agent.py")
WINDOW = os.path.join(LIB, "quiz-window.py")
UID = os.getuid()

STARTER = ("public class Main {\n    public static void main(String[] args) {\n        int age = 30;\n"
           "        boolean member = true;\n        int price;\n\n        // Write your code here\n\n    }\n}\n")
PACKAGE = {"quiz": "made-up", "title": "Made-up Quiz", "total": 5, "versions": [
    {"version": n, "questions": [
        {"qid": "q1", "text": f"What does this print? (version {n})", "code": f"System.out.println({n} + 1);",
         "marks": 2, "parts": [{"pid": "a", "prompt": "Output", "marks": 2, "kind": "output", "lines": 2, "run": False}]},
        {"qid": "q2", "text": "A ticket costs $10, members get $2 off. Print the price.", "code": "int age = 30;",
         "marks": 3, "parts": [{"pid": "a", "prompt": "Your code", "marks": 3, "kind": "code", "lines": 6,
                                "run": True, "starter": STARTER}]},
    ]} for n in range(4)]}


def load_agent():
    loader = importlib.machinery.SourceFileLoader("lab_quiz_agent", AGENT)
    spec = importlib.util.spec_from_loader("lab_quiz_agent", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def fake_command(path, log, script=""):
    with open(path, "w") as handle:
        handle.write(f"#!/bin/bash\n{{ echo \"$(basename $0) $*\"; [ -t 0 ] || cat; }} >> {log}\n{script}\n")
    os.chmod(path, 0o755)


class Agent(unittest.TestCase):
    """The agent with fake logins, systemd, nft, udev, cgroups and USB."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = lambda *parts: os.path.join(self.dir, *parts)
        for folder in ("bin", "state", "run", "home/tdsb-111", "cgroup", "usb", "udev"):
            os.makedirs(d(folder), exist_ok=True)
        self.log = d("calls.log")
        open(self.log, "w").close()
        self.sessions = d("sessions")
        self.active_units = d("active")
        os.makedirs(self.active_units)
        with open(self.sessions, "w") as handle:
            handle.write(f"2 {UID} tdsb-111 seat0 1234 user tty2 no -\n")
        fake_command(d("bin", "loginctl"), self.log, f"cat {self.sessions}")
        fake_command(d("bin", "systemctl"), self.log,
                     f'for a in "$@"; do case $a in *.service) [ -e {self.active_units}/$a ] && exit 0;; esac; done; '
                     f'[[ " $* " == *" is-active "* ]] && exit 3; exit 0')
        fake_command(d("bin", "systemd-run"), self.log,
                     f'for a in "$@"; do case $a in --unit=*) touch {self.active_units}/${{a#--unit=}};; esac; done')
        fake_command(d("bin", "nft"), self.log)
        fake_command(d("bin", "udevadm"), self.log)
        # A launched app, a session service and the quiz window in the student's app.slice.
        self.app_slice = d("cgroup", "user.slice", f"user-{UID}.slice", f"user@{UID}.service", "app.slice")
        for unit in ("app-gnome-intellij-2001.scope", "app-org.gnome.Terminal.slice", "dconf.service",
                     "snap.firefox.firefox-ab.scope", "lab-quiz-window-x.service", "dbus-:1.2-org.gnome.Nautilus@0.service"):
            os.makedirs(os.path.join(self.app_slice, unit))
            with open(os.path.join(self.app_slice, unit, "cgroup.procs"), "w") as handle:
                handle.write("4242\n")
        # USB: a stick (08), a phone (06) and a keyboard (03).
        for name, cls in (("1-1:1.0", "08"), ("1-2:1.0", "06"), ("1-3:1.0", "03")):
            os.makedirs(d("usb", name))
            for attr, value in (("bInterfaceClass", cls), ("authorized", "1")):
                with open(d("usb", name, attr), "w") as handle:
                    handle.write(value + "\n")
        # Keys: the teacher's (RSA) and this laptop's (ssh ed25519).
        self.teacher = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with open(d("teacher.pub.pem"), "wb") as handle:
            handle.write(self.teacher.public_key().public_bytes(serialization.Encoding.PEM,
                                                               serialization.PublicFormat.SubjectPublicKeyInfo))
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", d("laptop-key")], check=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", d("lab-key")], check=True)
        with open(d("lab-key.pub")) as handle:
            with open(d("allowed_signers"), "w") as out:
                out.write("lab@school " + handle.read())
        self.env = mock.patch.dict(os.environ, {
            "LAB_QUIZ_CONFIG": d("config"), "LAB_QUIZ_SIGNERS": d("allowed_signers"), "LAB_QUIZ_STATE": d("state"),
            "LAB_QUIZ_RUN": d("run"), "LAB_QUIZ_LAPTOP_KEY": d("laptop-key"), "LAB_QUIZ_TEACHER_KEY": d("teacher.pub.pem"),
            "LAB_QUIZ_HOSTNAME": "lab-test1", "LAB_QUIZ_CGROUP": d("cgroup"), "LAB_QUIZ_USB": d("usb"),
            "LAB_QUIZ_UDEV_RULE": d("udev", "70-lab-quiz-usb.rules"), "LAB_QUIZ_NFT": d("bin", "nft"),
            "LAB_QUIZ_LOGINCTL": d("bin", "loginctl"), "LAB_QUIZ_SYSTEMCTL": d("bin", "systemctl"),
            "LAB_QUIZ_SYSTEMD_RUN": d("bin", "systemd-run"), "LAB_QUIZ_UDEVADM": d("bin", "udevadm")})
        self.env.start()
        self.agent = load_agent()
        home = d("home", "tdsb-111")
        entry = types.SimpleNamespace(pw_name="tdsb-111", pw_uid=UID, pw_gid=UID, pw_dir=home)
        self.agent.pwd = types.SimpleNamespace(getpwnam=lambda name: entry if name == "tdsb-111" else
                                               (_ for _ in ()).throw(KeyError(name)),
                                               getpwuid=lambda uid: entry)
        self.agent.is_admin = lambda user: False
        self.agent.addresses = lambda host: ({"203.0.113.5"}, {"2001:db8::5"})
        self.home = home
        self.agent.prepare_submit_dir()
        os.makedirs(os.path.join(d("state"), "sittings"), exist_ok=True)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir)

    # helpers
    def signed(self, kind, body, sent=None):
        payload = json.dumps({"v": 1, "id": os.urandom(4).hex(), "sent": sent or int(time.time()), kind: body})
        path = os.path.join(self.dir, "payload")
        with open(path, "w") as handle:
            handle.write(payload)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", os.path.join(self.dir, "lab-key"), "-n",
                        "lab-message", path], check=True)
        with open(path + ".sig") as handle:
            signature = handle.read()
        os.unlink(path + ".sig")
        return json.dumps({"payload": payload, "sig": signature})

    def package_blob(self):
        key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        blob = nonce + AESGCM(key).encrypt(nonce, zlib.compress(json.dumps(PACKAGE).encode()), b"lab-quiz-package")
        return blob, hashlib.sha256(blob).hexdigest(), base64.b64encode(key).decode()

    def start(self, accounts=("tdsb-111",), laptops=None, sitting="made-up-20261020-0900"):
        blob, sha, key = self.package_blob()
        body = self.signed("quiz_start", {"sitting": sitting, "title": "Made-up Quiz", "total": 5,
                                          "url": "https://ntfy.example/file/x.bin", "sha256": sha, "key": key,
                                          "to_accounts": list(accounts) if accounts else None,
                                          "to_laptops": laptops})
        response = io.BytesIO(blob)
        response.__enter__ = lambda *a: response
        response.__exit__ = lambda *a: None
        with mock.patch.object(self.agent.urllib.request, "urlopen", return_value=response):
            message = self.agent.parse(body)
            self.assertIsNotNone(message)
            self.agent.handle(message)
        return sitting

    def calls(self):
        with open(self.log) as handle:
            return handle.read()

    def save_answers(self, sitting, answers, first="Sam ", last=" Student"):
        path = os.path.join(self.home, ".local", "state", "lab-quiz", f"{sitting}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            json.dump({"sitting": sitting, "first": first, "last": last, "answers": answers, "saved": 1}, handle)

    def read(self, *parts):
        with open(os.path.join(self.dir, *parts)) as handle:
            return handle.read()

    # tests
    def test_messages_must_be_signed_and_recent(self):
        body = self.signed("quiz_end", {"sitting": "made-up-1"})
        self.assertIsNotNone(self.agent.parse(body))
        tampered = json.loads(body)
        tampered["payload"] = tampered["payload"].replace("made-up-1", "made-up-2")
        self.assertIsNone(self.agent.parse(json.dumps(tampered)))
        self.assertIsNone(self.agent.parse(self.signed("quiz_end", {"sitting": "x"}, sent=time.time() - 6 * 3600)))
        self.assertIsNone(self.agent.parse("not json"))

    def test_quiz_opens_with_lockdown_then_hand_in_unlocks(self):
        sitting = self.start()
        laptop = self.agent.Laptop("https://ntfy.sh")
        laptop.tick()
        mine = json.loads(self.read("run", sitting, "tdsb-111.json"))
        self.assertEqual(mine["account"], "tdsb-111")
        self.assertEqual(mine["version"], self.agent.version_for(sitting, "tdsb-111", 4))
        self.assertEqual(oct(os.stat(os.path.join(self.dir, "run", sitting, "tdsb-111.json")).st_mode & 0o777), "0o400")
        self.assertEqual(json.loads(self.read("run", sitting, "tdsb-111.status")), {"state": "open"})
        calls = self.calls()
        self.assertIn(f"--unit=lab-quiz-window-{sitting}.service --slice=session.slice", calls)
        self.assertIn("table inet labquiz", calls)
        self.assertIn("203.0.113.5", calls)
        self.assertIn("disable-command-line true", calls)
        self.assertIn('ATTR{authorized}="0"', self.read("udev", "70-lab-quiz-usb.rules"))
        self.assertEqual([self.read("usb", n, "authorized").strip() for n in ("1-1:1.0", "1-2:1.0", "1-3:1.0")],
                         ["0", "0", "1"])                                       # stick + phone blocked, keyboard not
        killed = sorted(name for name in os.listdir(self.app_slice)
                        if os.path.exists(os.path.join(self.app_slice, name, "cgroup.kill")))
        self.assertEqual(killed, ["app-gnome-intellij-2001.scope", "app-org.gnome.Terminal.slice",
                                  "dbus-:1.2-org.gnome.Nautilus@0.service", "snap.firefox.firefox-ab.scope"])
        # Next round: the window is running, nothing restarted.
        open(self.log, "w").close()
        laptop.tick()
        self.assertNotIn("--unit=", self.calls())
        # The student hands in.
        self.save_answers(sitting, {"q1.a": "2", "q2.a": "price = 8;"})
        with open(os.path.join(self.dir, "run", "submit", "abc.json"), "w") as handle:
            json.dump({"sitting": sitting}, handle)
        laptop.tick()
        handed = json.loads(self.read("state", "sittings", sitting, "handed", "tdsb-111.json"))
        self.assertEqual((handed["how"], handed["answers"]["q2.a"]), ("submitted", "price = 8;"))
        self.assertEqual((handed["name"], handed["first"], handed["last"]), ("Sam Student", "Sam", "Student"))
        self.assertEqual(json.loads(self.read("run", sitting, "tdsb-111.status")), {"state": "handed"})
        self.assertIn("delete table inet labquiz", self.calls())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "udev", "70-lab-quiz-usb.rules")))
        self.assertEqual(self.read("usb", "1-1:1.0", "authorized").strip(), "1")
        self.assertIn("disable-command-line false", self.calls())
        # Handing in again changes nothing; the quiz doesn't reopen.
        open(self.log, "w").close()
        laptop.tick()
        self.assertNotIn("--unit=", self.calls())

    def test_only_targeted_accounts_and_laptops(self):
        self.start(accounts=("studenttest1",))
        self.agent.Laptop("https://ntfy.sh").tick()
        self.assertNotIn("--unit=", self.calls())
        self.assertNotIn("table inet labquiz {\n", self.calls())
        self.start(accounts=None, laptops=["lab-other"], sitting="made-up-2")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "state", "sittings", "made-up-2")))
        self.agent.is_admin = lambda user: True                                 # everyone-quizzes skip admins
        self.start(accounts=None, sitting="made-up-3")
        self.agent.Laptop("https://ntfy.sh").tick()
        self.assertNotIn("--unit=", self.calls())

    def test_teacher_ends_it_with_saved_answers(self):
        sitting = self.start()
        laptop = self.agent.Laptop("https://ntfy.sh")
        laptop.tick()
        self.save_answers(sitting, {"q1.a": "half done"})
        self.agent.handle(self.agent.parse(self.signed("quiz_end", {"sitting": sitting, "except": []})))
        laptop.tick()
        handed = json.loads(self.read("state", "sittings", sitting, "handed", "tdsb-111.json"))
        self.assertEqual((handed["how"], handed["answers"]), ("ended by teacher", {"q1.a": "half done"}))
        self.assertEqual(json.loads(self.read("run", sitting, "tdsb-111.status")), {"state": "ended"})
        self.assertIn("delete table inet labquiz", self.calls())

    def test_one_student_keeps_going(self):
        sitting = self.start()
        laptop = self.agent.Laptop("https://ntfy.sh")
        laptop.tick()
        self.agent.handle(self.agent.parse(self.signed("quiz_end", {"sitting": sitting, "except": ["TDSB-111"]})))
        laptop.tick()
        self.assertFalse(os.path.exists(os.path.join(self.dir, "state", "sittings", sitting, "handed")))
        self.assertTrue(laptop.locked)
        self.agent.handle(self.agent.parse(self.signed("quiz_end", {"sitting": sitting})))
        laptop.tick()
        self.assertFalse(laptop.locked)

    def test_logged_out_student_is_handed_in_at_the_end(self):
        sitting = self.start()
        laptop = self.agent.Laptop("https://ntfy.sh")
        laptop.tick()
        self.save_answers(sitting, {"q1.a": "2"})
        open(self.sessions, "w").close()                                       # logged out
        laptop.tick()
        self.assertFalse(laptop.locked)                                         # nobody writing here now
        self.agent.handle(self.agent.parse(self.signed("quiz_end", {"sitting": sitting})))
        laptop.tick()
        handed = json.loads(self.read("state", "sittings", sitting, "handed", "tdsb-111.json"))
        self.assertEqual(handed["answers"], {"q1.a": "2"})

    def test_late_login_and_restart_reopen_the_quiz(self):
        open(self.sessions, "w").close()
        sitting = self.start()
        self.agent.Laptop("https://ntfy.sh").tick()
        self.assertNotIn("--unit=", self.calls())
        with open(self.sessions, "w") as handle:
            handle.write(f"2 {UID} tdsb-111 seat0 1234 user tty2 no -\n")
        shutil.rmtree(os.path.join(self.dir, "run", sitting), ignore_errors=True)   # e.g. after a reboot
        self.agent.Laptop("https://ntfy.sh").tick()
        self.assertIn(f"--unit=lab-quiz-window-{sitting}.service", self.calls())

    def test_symlinked_save_file_is_not_read(self):
        sitting = self.start()
        self.agent.Laptop("https://ntfy.sh").tick()
        folder = os.path.join(self.home, ".local", "state", "lab-quiz")
        os.makedirs(folder, exist_ok=True)
        os.symlink("/etc/shadow", os.path.join(folder, f"{sitting}.json"))
        self.assertEqual(self.agent.saved_answers(sitting, "tdsb-111"), ({}, None, {"first": "", "last": "", "name": ""}))

    def test_hand_ins_are_signed_and_encrypted_for_the_teacher(self):
        sitting = self.start()
        laptop = self.agent.Laptop("https://ntfy.sh")
        laptop.tick()
        self.save_answers(sitting, {"q1.a": "2"})
        self.agent.handle(self.agent.parse(self.signed("quiz_end", {"sitting": sitting})))
        laptop.tick()
        posted = []

        def fake_open(request, timeout=None):
            posted.append(request.data)
            reply = io.BytesIO(b"{}")
            reply.__enter__ = lambda *a: reply
            reply.__exit__ = lambda *a: None
            return reply
        with mock.patch.object(self.agent.urllib.request, "urlopen", side_effect=fake_open):
            self.agent.send_outbox("https://ntfy.sh", "answers")
            self.agent.send_outbox("https://ntfy.sh", "answers")              # nothing sent twice
        self.assertEqual(len(posted), 2)                                        # opened + handed
        kinds = []
        for body in posted:
            outer = json.loads(body)
            self.assertNotIn("q1.a", body.decode())
            secret = self.teacher.decrypt(base64.b64decode(outer["key"]), padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            inner = json.loads(zlib.decompress(AESGCM(secret).decrypt(base64.b64decode(outer["nonce"]),
                                                                     base64.b64decode(outer["data"]), None)))
            message = json.loads(inner["message"])
            kinds.append(message["kind"])
            with open(os.path.join(self.dir, "signers"), "w") as handle:
                handle.write(f'laptop namespaces="lab-quiz" {inner["pubkey"]}\n')
            with open(os.path.join(self.dir, "sig"), "w") as handle:
                handle.write(inner["sig"])
            ok = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", os.path.join(self.dir, "signers"), "-I",
                                 "laptop", "-n", "lab-quiz", "-s", os.path.join(self.dir, "sig")],
                                input=inner["message"].encode(), capture_output=True)
            self.assertEqual(ok.returncode, 0)
            self.assertEqual((message["user"], message["laptop"]), ("tdsb-111", "lab-test1"))
        self.assertEqual(sorted(kinds), ["handed", "opened"])
        self.agent.handle(self.agent.parse(self.signed("quiz_resend", {"sitting": sitting})))
        with mock.patch.object(self.agent.urllib.request, "urlopen", side_effect=fake_open):
            self.agent.send_outbox("https://ntfy.sh", "answers")
        self.assertEqual(len(posted), 4)

    def test_bad_package_is_refused_and_retried(self):
        blob, sha, key = self.package_blob()
        body = self.signed("quiz_start", {"sitting": "made-up-9", "title": "x", "total": 5, "url": "https://x/f",
                                          "sha256": "0" * 64, "key": key, "to_accounts": ["tdsb-111"]})
        response = io.BytesIO(blob)
        response.__enter__ = lambda *a: response
        response.__exit__ = lambda *a: None
        with mock.patch.object(self.agent.urllib.request, "urlopen", return_value=response):
            self.agent.handle(self.agent.parse(body))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "state", "sittings", "made-up-9", "package.json")))
        self.agent.Laptop("https://ntfy.sh").tick()
        self.assertNotIn("--unit=", self.calls())

    @unittest.skipUnless(shutil.which("unshare") and os.path.exists("/usr/sbin/nft"), "needs unshare + nft")
    def test_firewall_rules_are_valid_nft(self):
        captured = {}
        self.agent.nft = lambda script: captured.setdefault("script", script) and types.SimpleNamespace(returncode=0)
        self.agent.firewall_on("ntfy.sh", {"4": set(), "6": set()})
        check = subprocess.run(["unshare", "-rn", "/usr/sbin/nft", "-c", "-f", "-"], input=captured["script"],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)


@unittest.skipUnless(shutil.which("gtk4-broadwayd") and shutil.which("java"), "needs gtk4-broadwayd and java")
class Window(unittest.TestCase):
    """The real quiz window on a private Broadway display (never the user's screen)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.display = f":{40 + os.getpid() % 50}"
        self.runtime = os.path.join(self.dir, "runtime")
        os.makedirs(self.runtime, mode=0o700)
        self.broadway = subprocess.Popen(["gtk4-broadwayd", self.display], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, env=dict(os.environ, XDG_RUNTIME_DIR=self.runtime))
        time.sleep(1)
        self.run_dir = os.path.join(self.dir, "run")
        self.sitting = "made-up-20261020-0900"
        os.makedirs(os.path.join(self.run_dir, self.sitting))
        os.makedirs(os.path.join(self.run_dir, "submit"))
        self.user = __import__("pwd").getpwuid(UID).pw_name
        version = PACKAGE["versions"][1]
        with open(os.path.join(self.run_dir, self.sitting, f"{self.user}.json"), "w") as handle:
            json.dump({"sitting": self.sitting, "title": "Made-up Quiz", "total": 5, "account": self.user, **version},
                      handle)
        self.home = os.path.join(self.dir, "home")
        os.makedirs(self.home)

    def tearDown(self):
        self.broadway.terminate()
        self.broadway.wait()
        shutil.rmtree(self.dir)

    def window(self, script, status=None, countdown=1):
        env = dict(os.environ, HOME=self.home, LAB_QUIZ_COUNTDOWN=str(countdown), GDK_BACKEND="broadway", BROADWAY_DISPLAY=self.display,
                   XDG_RUNTIME_DIR=self.runtime, LAB_QUIZ_RUN=self.run_dir, LAB_QUIZ_WINDOWED="1",
                   LAB_QUIZ_APP_ID=f"com.school.LabQuizTest{os.getpid()}{int(time.time() * 1000) % 100000}",
                   LAB_QUIZ_SELFTEST=json.dumps(script))
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        process = subprocess.Popen([sys.executable, "-I", WINDOW, self.sitting], env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        if status:                                       # play the agent: answer the hand-in
            submit = os.path.join(self.run_dir, "submit")
            for _ in range(100):
                if os.listdir(submit):
                    break
                time.sleep(0.2)
            self.assertTrue(os.listdir(submit), "no hand-in dropped")
            with open(os.path.join(self.run_dir, self.sitting, f"{self.user}.status"), "w") as handle:
                json.dump({"state": status}, handle)
        out, err = process.communicate(timeout=90)
        self.assertEqual(process.returncode, 0, err)
        return json.loads(out.strip().splitlines()[-1])

    def saved(self):
        with open(os.path.join(self.home, ".local", "state", "lab-quiz", f"{self.sitting}.json")) as handle:
            return json.load(handle)

    def test_starter_reset_and_run(self):
        shown = self.window({"first": "Sam", "last": "Lee"})
        self.assertEqual(shown["starters"], ["q2.a"])                           # only the Run question
        self.assertEqual(shown["answers"]["q2.a"], STARTER)                      # starts with the whole program
        self.assertEqual(shown["answers"]["q1.a"], "")
        program = STARTER.replace("        // Write your code here\n",
                                  "        price = 10;\n        if (member) { price -= 2; }\n"
                                  "        System.out.println(\"Price: $\" + price);\n")
        shown = self.window({"answers": {"q1.a": "2", "q2.a": program}, "run": "q2.a"})
        self.assertEqual(shown["run_buttons"], ["q2.a"])
        self.assertEqual(shown["run_output"]["q2.a"].strip(), "Price: $8")
        self.assertEqual(self.saved()["answers"]["q2.a"], program)
        shown = self.window({"answers": {"q2.a": "oops, I deleted everything"}, "reset": "q2.a"})
        self.assertEqual(shown["answers"]["q2.a"], STARTER)
        self.assertEqual(self.saved()["answers"]["q2.a"], STARTER)

    def test_run_shows_compile_problems(self):
        shown = self.window({"first": "Sam", "last": "Lee", "answers": {"q2.a": STARTER.replace("int price;", "int price = ;")},
                             "run": "q2.a"})
        self.assertIn("Problem:", shown["run_output"]["q2.a"])

    def test_saved_answers_come_back_after_a_crash(self):
        os.makedirs(os.path.join(self.home, ".local", "state", "lab-quiz"))
        with open(os.path.join(self.home, ".local", "state", "lab-quiz", f"{self.sitting}.json"), "w") as handle:
            json.dump({"first": "Sam", "last": "Lee", "answers": {"q1.a": "from before"}}, handle)
        shown = self.window({})
        self.assertEqual((shown["first_page"], shown["name"]), ("quiz", "Sam Lee"))       # not asked again
        self.assertTrue(shown["sidebar"][0].startswith("✓"))

    def test_name_page_first_and_last_and_id(self):
        shown = self.window({})
        self.assertEqual((shown["first_page"], shown["page"]), ("name", "name"))
        self.assertIn(f"ID {self.user}", shown["who"])                           # test account: ID = account
        shown = self.window({"first": "Sam"})                                     # last name missing: still asked
        self.assertEqual((shown["page"], shown["name"]), ("name", ""))
        shown = self.window({"first": "  Sam ", "last": " Van  Lee "})
        self.assertEqual((shown["page"], shown["first"], shown["last"]), ("quiz", "Sam", "Van Lee"))
        self.assertEqual((self.saved()["first"], self.saved()["last"], self.saved()["name"]), ("Sam", "Van Lee", "Sam Van Lee"))

    def test_edit_name(self):
        self.window({"first": "Sam", "last": "Lee"})
        shown = self.window({"edit_name": ["Samantha", "Lee"]})
        self.assertEqual((shown["edit_page"], shown["edit_button"]), ("name", "Save and go back to the quiz"))
        self.assertEqual((shown["page"], shown["name"]), ("quiz", "Samantha Lee"))
        self.assertEqual(self.saved()["first"], "Samantha")

    def test_hand_in_needs_the_words(self):
        shown = self.window({"first": "Sam", "last": "Lee", "handin": "hand it"})
        self.assertEqual((shown["handin_page"], shown["confirm_ok"], shown["countdown_seen"]), ("handin", False, None))
        self.assertFalse(os.listdir(os.path.join(self.run_dir, "submit")))

    def test_countdown_can_be_cancelled(self):
        shown = self.window({"first": "Sam", "last": "Lee", "handin": "HAND IN", "cancel": True}, countdown=5)
        self.assertTrue(shown["countdown_seen"])
        self.assertTrue(shown["cancelled"])
        self.assertEqual((shown["page"], shown["state"]), ("quiz", "open"))
        self.assertFalse(os.listdir(os.path.join(self.run_dir, "submit")))       # nothing handed in

    def test_hand_in_after_countdown(self):
        shown = self.window({"first": "Sam", "last": "Lee", "answers": {"q1.a": "2"}, "handin": " hand  in "},
                            status="handed", countdown=2)
        self.assertTrue(shown["countdown_seen"])
        self.assertEqual(shown["state"], "handed")
        self.assertEqual(self.saved()["answers"]["q1.a"], "2")


class Power(unittest.TestCase):
    def files(self, *parts):
        return os.path.join(UPDATE, "files", *parts)

    def read(self, *parts):
        with open(self.files(*parts)) as handle:
            return handle.read()

    def test_settings_and_locks(self):
        settings = self.read("etc", "dconf", "db", "local.d", "50-lab-power")
        for line in ("show-battery-percentage=true", "idle-delay=uint32 0", "sleep-inactive-ac-type='nothing'",
                     "sleep-inactive-battery-type='nothing'", "power-saver-profile-on-low-battery=false"):
            self.assertIn(line, settings)
        locks = self.read("etc", "dconf", "db", "local.d", "locks", "50-lab-power").split()
        self.assertEqual(len(locks), 6)
        for key in locks:                                                        # every lock names a set key
            self.assertIn(key.rsplit("/", 1)[1] + "=", settings)
        greeter = self.read("usr", "share", "gdm", "dconf", "98-lab-power")
        self.assertIn("sleep-inactive-battery-type='nothing'", greeter)
        for key in self.read("usr", "share", "gdm", "dconf", "locks", "98-lab-power-locks").split():
            self.assertIn(key.rsplit("/", 1)[1] + "=", greeter)

    @unittest.skipUnless(shutil.which("dconf"), "needs dconf")
    def test_settings_compile(self):
        work = tempfile.mkdtemp()
        try:
            shutil.copytree(self.files("etc", "dconf", "db", "local.d"), os.path.join(work, "local.d"))
            subprocess.run(["dconf", "compile", os.path.join(work, "local"), os.path.join(work, "local.d")], check=True)
        finally:
            shutil.rmtree(work)

    def test_performance_script(self):
        work = tempfile.mkdtemp()
        try:
            log = os.path.join(work, "log")
            fake = os.path.join(work, "powerprofilesctl")
            for current, supported, expect in (("balanced", True, "balanced -> performance"),
                                               ("performance", True, ""),
                                               ("balanced", False, "no Performance mode")):
                with open(fake, "w") as handle:
                    handle.write(f"#!/bin/bash\necho \"$*\" >> {log}\n[ \"$1\" = get ] && echo {current}\n"
                                 f"[ \"$1\" = set ] && exit {0 if supported else 1}\nexit 0\n")
                os.chmod(fake, 0o755)
                out = subprocess.run(["bash", self.files("usr", "local", "sbin", "lab-performance")], capture_output=True,
                                     text=True, env=dict(os.environ, PATH=work + ":" + os.environ["PATH"]))
                self.assertEqual(out.returncode, 0)
                self.assertIn(expect, out.stdout)
        finally:
            shutil.rmtree(work)


class InstallScript(unittest.TestCase):
    def test_install_script(self):
        folder = UPDATE
        with open(os.path.join(folder, "install.sh")) as handle:
            script = handle.read()
        for path in ("usr/local/lib/lab-quiz/lab-quiz-agent.py", "usr/local/lib/lab-quiz/quiz-window.py",
                     "etc/dconf/db/local.d/50-lab-power", "etc/dconf/db/local.d/locks/50-lab-power",
                     "usr/share/gdm/dconf/98-lab-power", "usr/share/gdm/dconf/locks/98-lab-power-locks",
                     "usr/local/sbin/lab-performance", "etc/systemd/system/lab-performance.service",
                     "etc/systemd/system/lab-performance.timer"):
            self.assertIn("files/" + path, script)
            self.assertTrue(os.path.exists(os.path.join(folder, "files", path)))
        for line in ("systemctl restart lab-quiz.service", "dconf update", "systemctl enable --now lab-performance.timer",
                     "/usr/share/gdm/generate-config"):
            self.assertIn(line, script)
        subprocess.run(["bash", "-n", os.path.join(folder, "install.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
