#!/usr/bin/env python3
"""Tests for 0039-quiz-feedback: a quiz start can carry a feedback file (the
answer keys, encrypted to each laptop's message key); the agent opens it only
if it is addressed to this laptop, grades a hand-in on the laptop (quizgrade:
the teacher's grader), writes the student's feedback file, keeps the student
in exam mode until the teacher ends the quiz, and the window shows the marks
over the answers. Every older quiz agent (0028, 0036, 0038) and window (0028,
0030, 0036) test reruns on the new files.
Fakes only: no network, no root, no real firewall (Java runs for the grader).

    python3 -I update-repo/tests/test_0039_quiz_feedback.py
"""

import base64
import json
import os
import subprocess
import sys
import time
import unittest
import zlib
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0039-quiz-feedback")
LIB = os.path.join(UPDATE, "files", "usr", "local", "lib", "lab-quiz")
AGENT = os.path.join(LIB, "lab-quiz-agent.py")
WINDOW = os.path.join(LIB, "quiz-window.py")
GRADER = os.path.join(LIB, "quizgrade.py")

sys.path.insert(0, HERE)
import test_0028_quiz_improvements_power as t28   # noqa: E402
import test_0030_quiz_choices_input as t30   # noqa: E402
import test_0036_lab_sounds as t36   # noqa: E402
import test_0038_lab_message_server as t38   # noqa: E402

t28.AGENT = AGENT
t28.WINDOW = WINDOW
t30.WINDOW = WINDOW

# The made-up quiz (test_0028's PACKAGE) with its keys: q1 prints n + 1, q2 the member price.
CASES = [{"inputs": [age, member], "expect": str(10 - (2 if member else 0))}
         for age in (12, 30) for member in (False, True)]
GRADING = {"quiz": "made-up", "versions": [
    {"version": n, "questions": [
        {"qid": "q1", "parts": [{"pid": "a", "marks": 2, "kind": "output",
                                 "grader": {"kind": "output", "expect": f"{n + 1}"}}]},
        {"qid": "q2", "parts": [{"pid": "a", "marks": 3, "kind": "code",
                                 "grader": {"kind": "statements", "inputs": [["int", "age"], ["boolean", "member"]],
                                            "output": ["int", "price"], "print": None, "expect_number": True,
                                            "cases": CASES, "run_with": [30, True]},
                                 "model": "price = 10;\nif (member) {\n    price = price - 2;\n}\n"
                                          "System.out.println(price);"}]},
    ]} for n in range(4)]}
RIGHT_Q2 = t28.STARTER.replace("        // Write your code here\n",
                               "        price = 10;\n        if (member) { price = price - 2; }\n"
                               "        System.out.println(price);\n")


def envelope(laptop_keys, data):
    """The teacher's feedback file (a copy of tools/labquiz/sittings.feedback_envelope)."""
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")
    secret = AESGCM.generate_key(bit_length=256)
    ephemeral = x25519.X25519PrivateKey.generate()
    epk = ephemeral.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    recipients = {}
    for name, public_b64 in sorted(laptop_keys.items()):
        public = base64.b64decode(public_b64)
        shared = ephemeral.exchange(x25519.X25519PublicKey.from_public_bytes(public))
        kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                   info=b"lab-quiz-feedback-v1" + epk + public).derive(shared)
        nonce = os.urandom(12)
        recipients[name] = b64(nonce + AESGCM(kek).encrypt(nonce, secret, b"lab-quiz-feedback-key"))
    nonce = os.urandom(12)
    return json.dumps({"lab_quiz_feedback": 1, "epk": b64(epk), "to": recipients, "nonce": b64(nonce),
                       "data": b64(AESGCM(secret).encrypt(nonce, zlib.compress(data, 9), b"lab-quiz-feedback"))
                       }).encode("utf-8")


# ---------------------------------------------------------------- older tests on the new files

class Old0028Agent(t28.Agent):
    pass


class Old0028Window(t28.Window):
    pass


class Old0030Choices(t30.Choices):
    pass


class Old0036Countdown(t36.EndCountdown):
    pass


class Old0036WindowSounds(t36.WindowSounds):
    pass


class Old0038AgentServers(t38.AgentServers):
    pass


# ---------------------------------------------------------------- the laptop's grader

class Grader(unittest.TestCase):
    def setUp(self):
        os.environ["LAB_QUIZ_GRADE_SANDBOX"] = "0"
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("quizgrade39", GRADER)
        spec = importlib.util.spec_from_loader("quizgrade39", loader)
        self.module = importlib.util.module_from_spec(spec)
        loader.exec_module(self.module)

    def tearDown(self):
        os.environ.pop("LAB_QUIZ_GRADE_SANDBOX", None)

    def test_sandbox_command_drops_to_nobody_offline(self):
        calls = []
        self.module.SANDBOX = True
        with mock.patch.object(self.module.subprocess, "run",
                               side_effect=lambda command, **kw: calls.append((command, kw)) or
                               subprocess.CompletedProcess(command, 0, "", "")):
            self.module.run_java("class Main {}")
        command, options = calls[0]
        self.assertEqual(command[:3], ["/usr/bin/unshare", "--net", "--"])
        self.assertIn("--reuid=65534", command)
        self.assertIn("--clear-groups", command)
        self.assertEqual(command[-1], "Main.java")
        self.assertEqual(options["timeout"], 20)

    def test_statements_graded_like_the_teacher(self):
        part = GRADING["versions"][0]["questions"][1]["parts"][0]
        right = self.module.grade_part(part, RIGHT_Q2)
        self.assertEqual((right["suggested"], right["summary"]), (3, "Passed 4 of 4 tests"))
        wrong = self.module.grade_part(part, t28.STARTER.replace("        // Write your code here\n",
                                                                 "        price = 10;\n        System.out.println(price);\n"))
        self.assertEqual(wrong["summary"], "Passed 2 of 4 tests")
        self.assertEqual(len(wrong["details"]), 2)
        broken = self.module.grade_part(part, "price = ;")
        self.assertEqual((broken["suggested"], broken["summary"]), (0, "Doesn't compile or run."))

    def test_choice_and_output_need_no_java(self):
        choice = {"marks": 1, "grader": {"kind": "choice", "answer": "c"}}
        self.assertEqual(self.module.grade_part(choice, "C")["suggested"], 1)
        self.assertEqual(self.module.grade_part(choice, "b")["suggested"], 0)
        self.assertEqual(self.module.grade_part(choice, "")["summary"], "No answer.")
        output = {"marks": 2, "grader": {"kind": "output", "expect": "5\nhi"}}
        self.assertEqual(self.module.grade_part(output, "5\nhi")["suggested"], 2)
        self.assertEqual(self.module.grade_part(output, "5\nho")["suggested"], 1)


# ---------------------------------------------------------------- the agent

class Feedback(t28.Agent):
    def setUp(self):
        super().setUp()
        self.message_key = x25519.X25519PrivateKey.generate()
        path = os.path.join(self.dir, "message-key")
        with open(path, "wb") as handle:
            handle.write(self.message_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                        serialization.NoEncryption()))
        self.agent.MESSAGE_KEY = path
        self.agent.GRADER = GRADER
        os.environ["LAB_QUIZ_GRADE_SANDBOX"] = "0"
        self.agent.os.chown = lambda *a: None

    def tearDown(self):
        os.environ.pop("LAB_QUIZ_GRADE_SANDBOX", None)
        super().tearDown()

    def public(self, key=None):
        key = key or self.message_key
        return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                              serialization.PublicFormat.Raw)).decode()

    def start_with_feedback(self, laptops=None):
        sitting = self.start()
        blob = envelope(laptops or {"lab-test1": self.public()}, json.dumps(GRADING).encode())
        path = os.path.join(self.dir, "state", "sittings", sitting, "start.json")
        with open(path) as handle:
            record = json.load(handle)
        record["feedback"] = {"url": "https://ntfy.example/file/f.bin", "mirrors": [],
                              "sha256": __import__("hashlib").sha256(blob).hexdigest()}
        with open(path, "w") as handle:
            json.dump(record, handle)
        self.blob = blob
        return sitting, record

    def tick(self, laptop, times=1):
        with mock.patch.object(self.agent, "fetch", side_effect=lambda url, sha: self.blob):
            for _ in range(times):
                laptop.tick()

    def wait_feedback(self, sitting):
        for _ in range(200):
            if not self.agent.GRADING_NOW and os.path.exists(self.agent.feedback_path(sitting, "tdsb-111")):
                with open(self.agent.feedback_path(sitting, "tdsb-111")) as handle:
                    return json.load(handle)
            time.sleep(0.1)
        self.fail("no feedback file")

    def status(self, sitting):
        return json.loads(self.read("run", sitting, "tdsb-111.status"))

    def hand_in_now(self, sitting):
        with open(os.path.join(self.dir, "run", "submit", "x.json"), "w") as handle:
            json.dump({"sitting": sitting}, handle)

    def test_start_keeps_the_feedback_link(self):
        sitting = "made-up-20261020-0900"
        blob, sha, key = self.package_blob()
        body = self.signed("quiz_start", {"sitting": sitting, "title": "T", "total": 5, "url": "https://a/x",
                                          "sha256": sha, "key": key, "to_accounts": None, "to_laptops": None,
                                          "feedback": {"url": "https://a/f", "sha256": "ab",
                                                       "mirrors": ["https://lab/f", "http://bad"]}})
        with mock.patch.object(self.agent, "download_any", return_value=t28.PACKAGE):
            self.agent.handle(self.agent.parse(body))
        record = json.loads(self.read("state", "sittings", sitting, "start.json"))
        self.assertEqual(record["feedback"], {"url": "https://a/f", "sha256": "ab", "mirrors": ["https://lab/f"]})

    def test_feedback_file_opens_only_on_its_laptops(self):
        other = x25519.X25519PrivateKey.generate()
        self.assertEqual(self.agent.open_feedback(envelope({"lab-test1": self.public()}, b'{"versions": []}')),
                         {"versions": []})
        self.assertIsNone(self.agent.open_feedback(envelope({"lab-other": self.public(other)}, b"{}")))
        with self.assertRaises(Exception):          # addressed to this name, but another laptop's key
            self.agent.open_feedback(envelope({"lab-test1": self.public(other)}, b"{}"))

    def test_hand_in_graded_then_marks_until_the_teacher_ends(self):
        sitting, record = self.start_with_feedback()
        laptop = self.agent.Laptop("https://ntfy.sh")
        self.tick(laptop)
        self.assertIsNotNone(self.agent.grading_for(sitting))
        mode = os.stat(self.agent.grading_path(sitting)).st_mode & 0o777
        self.assertEqual(mode, 0o600)                                 # root only
        self.assertTrue(laptop.locked)
        version = self.agent.version_for(sitting, "tdsb-111", 4)
        self.save_answers(sitting, {"q1.a": str(version + 1), "q2.a": "oops"})
        self.hand_in_now(sitting)
        self.tick(laptop)
        feedback = self.wait_feedback(sitting)
        self.assertEqual((feedback["earned"], feedback["out_of"]), (1, 5))      # 1 mark per output line
        self.assertEqual(feedback["parts"]["q1.a"]["summary"], "1 of 1 lines exactly right")
        self.assertEqual(feedback["parts"]["q1.a"]["correct"], str(version + 1))
        self.assertEqual(feedback["parts"]["q2.a"]["earned"], 0)
        self.assertIn("System.out.println(price);", feedback["parts"]["q2.a"]["correct"])
        self.tick(laptop)
        self.assertEqual(self.status(sitting), {"state": "handed", "feedback": True})
        self.assertTrue(laptop.locked)                                 # still in exam mode
        self.assertIn("tdsb-111", laptop.locked_users)
        self.agent.handle_end(self.agent.parse(self.signed("quiz_end", {"sitting": sitting})))
        self.tick(laptop)
        self.assertEqual(self.status(sitting), {"state": "handed", "feedback": True, "over": True})
        self.assertFalse(laptop.locked)

    def test_regraded_after_a_reboot(self):
        sitting, record = self.start_with_feedback()
        laptop = self.agent.Laptop("https://ntfy.sh")
        self.tick(laptop)
        self.save_answers(sitting, {"q1.a": "nope"})
        self.hand_in_now(sitting)
        self.tick(laptop)
        self.wait_feedback(sitting)
        import shutil
        shutil.rmtree(os.path.join(self.dir, "run", sitting))         # /run is empty after a reboot
        self.tick(laptop)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "run", sitting, "tdsb-111.json")))
        self.assertEqual(self.wait_feedback(sitting)["earned"], 0)
        self.assertTrue(laptop.locked)

    def test_laptop_not_in_the_list_hands_in_as_before(self):
        other = x25519.X25519PrivateKey.generate()
        sitting, record = self.start_with_feedback({"lab-other": self.public(other)})
        laptop = self.agent.Laptop("https://ntfy.sh")
        self.tick(laptop)
        self.assertIsNone(self.agent.grading_for(sitting))
        self.save_answers(sitting, {"q1.a": "1"})
        self.hand_in_now(sitting)
        self.tick(laptop)
        self.assertEqual(self.status(sitting), {"state": "handed"})
        self.assertFalse(os.path.exists(self.agent.feedback_path(sitting, "tdsb-111")))
        self.assertFalse(laptop.locked)

    def test_ended_by_teacher_still_gets_marks(self):
        sitting, record = self.start_with_feedback()
        laptop = self.agent.Laptop("https://ntfy.sh")
        self.tick(laptop)
        version = self.agent.version_for(sitting, "tdsb-111", 4)
        self.save_answers(sitting, {"q1.a": str(version + 1), "q2.a": RIGHT_Q2})
        self.agent.handle_end(self.agent.parse(self.signed("quiz_end", {"sitting": sitting})))
        self.tick(laptop)
        self.assertEqual(self.wait_feedback(sitting)["earned"], 4)
        self.tick(laptop)
        self.assertEqual(self.status(sitting), {"state": "ended", "feedback": True, "over": True})
        self.assertFalse(laptop.locked)

    def test_grade_written_choice_and_broken_java(self):
        version = {"questions": [
            {"qid": "q1", "parts": [{"pid": "1", "marks": 0.5, "kind": "choice", "options": [["T", "True"], ["F", "False"]],
                                     "grader": {"kind": "choice", "answer": "T"}},
                                    {"pid": "2", "marks": 1, "kind": "choice",
                                     "options": [["a", "x"], ["b", "y"], ["c", "z"], ["d", "w"]],
                                     "grader": {"kind": "choice", "answer": "c"}}]},
            {"qid": "q5", "parts": [{"pid": "a", "marks": 1, "kind": "text"}]},
            {"qid": "q4", "parts": [{"pid": "a", "marks": 2, "kind": "code", "model": "a && b",
                                     "grader": {"kind": "condition", "params": [["boolean", "a"], ["boolean", "b"]],
                                                "cases": [{"inputs": [True, True], "expect": "true"},
                                                          {"inputs": [True, False], "expect": "false"}]}}]}]}
        answers = {"q1.1": "F", "q1.2": "c", "q5.a": "words", "q4.a": "a && b"}
        result = self.agent.grade(version, answers)
        self.assertEqual(result["parts"]["q1.1"], {"marks": 0.5, "earned": 0, "summary": "Not right.", "details": [],
                                                   "correct": "True"})
        self.assertEqual(result["parts"]["q1.2"]["summary"], "Right.")
        self.assertEqual(result["parts"]["q5.a"], {"marks": 1, "earned": None, "summary": "Your teacher marks this."})
        self.assertEqual(result["parts"]["q4.a"]["earned"], 2)
        self.assertEqual((result["earned"], result["out_of"], result["teacher_marks"]), (3, 3.5, 1))
        answers["q1.2"] = "a"
        self.assertEqual(self.agent.grade(version, answers)["parts"]["q1.2"]["correct"], "c) z")
        self.agent.JAVA_CHECK["ok"] = False                             # the sandbox doesn't work here
        broken = self.agent.grade(version, answers)
        self.assertIsNone(broken["parts"]["q4.a"]["earned"])
        self.assertEqual(broken["teacher_marks"], 3)


# ---------------------------------------------------------------- the window

class ReviewWindow(t28.Window):
    def review(self, feedback, answers, over=True):
        """Hand in, then play the agent: grading, the marks, the teacher's end."""
        env = dict(os.environ, HOME=self.home, LAB_QUIZ_COUNTDOWN="1", GDK_BACKEND="broadway",
                   BROADWAY_DISPLAY=self.display, XDG_RUNTIME_DIR=self.runtime, LAB_QUIZ_RUN=self.run_dir,
                   LAB_QUIZ_WINDOWED="1", LAB_QUIZ_APP_ID=f"com.school.LabQuizTest{os.getpid()}{int(time.time() * 1000) % 100000}",
                   LAB_QUIZ_SELFTEST=json.dumps({"first": "Sam", "last": "Lee", "answers": answers,
                                                 "handin": "HAND IN", "wait_review": True, "wait_over": over}))
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        process = subprocess.Popen([sys.executable, "-I", WINDOW, self.sitting], env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        status = os.path.join(self.run_dir, self.sitting, f"{self.user}.status")
        submit = os.path.join(self.run_dir, "submit")
        for _ in range(100):
            if os.listdir(submit):
                break
            time.sleep(0.2)
        self.assertTrue(os.listdir(submit), "no hand-in dropped")
        with open(status, "w") as handle:
            json.dump({"state": "handed", "grading": True}, handle)
        time.sleep(3)
        if feedback is not None:
            with open(os.path.join(self.run_dir, self.sitting, f"{self.user}.feedback"), "w") as handle:
                json.dump(feedback, handle)
            with open(status, "w") as handle:
                json.dump({"state": "handed", "feedback": True}, handle)
            time.sleep(3)
        if over:
            with open(status, "w") as handle:
                json.dump({"state": "handed", "feedback": True, "over": True}, handle)
        out, err = process.communicate(timeout=90)
        self.assertEqual(process.returncode, 0, err)
        return json.loads(out.strip().splitlines()[-1])

    FEEDBACK = {"earned": 2, "out_of": 5, "teacher_marks": 0, "parts": {
        "q1.a": {"marks": 2, "earned": 2, "summary": "1 of 1 lines exactly right", "details": []},
        "q2.a": {"marks": 3, "earned": 0, "summary": "Passed 0 of 4 tests",
                 "details": ["age=12, member=false: expected 10, got (no number printed)"],
                 "correct": "price = 10;\nif (member) {\n    price = price - 2;\n}\nSystem.out.println(price);"}}}

    def test_marks_over_the_answers_then_close_when_over(self):
        shown = self.review(self.FEEDBACK, {"q1.a": "3"})
        self.assertTrue(shown["reviewing"])
        self.assertTrue(shown["review"].startswith("Handed in ✓   Your mark: 2 / 5"))
        self.assertIn("You can close this window.", shown["review"])
        self.assertEqual(shown["editable"], [])                        # answers locked
        self.assertTrue(shown["feedback"]["q1.a"][0].startswith("✓ 2/2 marks"))
        self.assertTrue(shown["feedback"]["q2.a"][0].startswith("✗ 0/3 marks  ·  Passed 0 of 4 tests"))
        self.assertIn("A correct answer:", shown["feedback"]["q2.a"][0])
        self.assertIn("System.out.println(price);", shown["feedback"]["q2.a"][1])
        self.assertEqual(shown["sidebar"], ["✓ Question 1  ·  2/2", "✗ Question 2  ·  0/3"])
        self.assertTrue(shown["over"])
        self.assertTrue(shown["close_visible"])
        self.assertEqual(shown["page"], "quiz")

    def test_marks_shown_but_not_closable_before_the_end(self):
        shown = self.review(self.FEEDBACK, {"q1.a": "3"}, over=False)
        self.assertIsNotNone(shown["review"])
        self.assertIn("Stay in the quiz until your teacher ends it.", shown["review"])
        self.assertFalse(shown["over"])
        self.assertFalse(shown["close_visible"])

    def test_grading_failed_then_ended(self):
        shown = self.review(None, {"q1.a": "3"})
        self.assertIsNone(shown["review"])
        self.assertEqual(shown["done"], ["Handed in ✓", "Your teacher ended the quiz. You can close this window."])
        self.assertTrue(shown["close_visible"])


# ---------------------------------------------------------------- install

class InstallScript(unittest.TestCase):
    def test_installs_every_file_it_ships(self):
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read()
        shipped = sorted(os.path.relpath(os.path.join(root, name), os.path.join(UPDATE, "files"))
                         for root, _dirs, names in os.walk(os.path.join(UPDATE, "files")) for name in names
                         if "__pycache__" not in root)
        for path in shipped:
            self.assertIn(f"files/{path}", script)
        self.assertIn('source "$LAB_UPDATER_HELPERS"', script)
        self.assertIn("systemctl restart lab-quiz.service", script)

    def test_programs_compile(self):
        for path in (AGENT, WINDOW, GRADER):
            with open(path) as handle:
                compile(handle.read(), path, "exec")


if __name__ == "__main__":
    unittest.main()
