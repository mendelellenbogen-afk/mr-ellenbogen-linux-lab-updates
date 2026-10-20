#!/usr/bin/env python3
"""Tests for 0030-quiz-choices-input: the quiz window with True/False and
multiple-choice buttons, a code snippet per part, question titles, half marks
and an Input box for Run questions that read the keyboard. Also re-runs the
0028 window tests against the 0030 window (nothing it did may break). The
window runs on a private Broadway display; a small made-up quiz (this repo is
public).

    python3 -I update-repo/tests/test_0030_quiz_choices_input.py
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_0028_quiz_improvements_power as t28  # noqa: E402

UPDATE = os.path.join(HERE, "..", "updates", "0030-quiz-choices-input")
WINDOW = os.path.join(UPDATE, "files", "usr", "local", "lib", "lab-quiz", "quiz-window.py")

KEYBOARD_STARTER = ("import java.util.Scanner;\n\npublic class Main {\n    public static void main(String[] args) {\n"
                    "        Scanner input = new Scanner(System.in);\n\n        // Write your code here\n\n    }\n}\n")
SUM_PROGRAM = KEYBOARD_STARTER.replace("        // Write your code here\n",
                                       "        int a = input.nextInt();\n        int b = input.nextInt();\n"
                                       "        System.out.println(\"Sum: \" + (a + b));\n")

CHOICE_VERSION = {"version": 0, "questions": [
    {"qid": "q1", "title": "Part A: True/False", "text": "True or false?", "code": "", "marks": 1.0, "parts": [
        {"pid": "1", "prompt": "A made-up statement.", "marks": 0.5, "kind": "choice",
         "options": [["T", "True"], ["F", "False"]], "run": False},
        {"pid": "2", "prompt": "Another made-up statement.", "marks": 0.5, "kind": "choice",
         "options": [["T", "True"], ["F", "False"]], "run": False}]},
    {"qid": "q2", "title": "Part A: Multiple choice", "text": "Choose one.", "code": "", "marks": 1, "parts": [
        {"pid": "1", "prompt": "What is printed?", "marks": 1, "kind": "choice", "code": "System.out.println(1 + 1);",
         "options": [["a", "11"], ["b", "2"], ["c", "1 + 1"], ["d", "A compilation error occurs."]], "run": False}]},
    {"qid": "q3", "title": "Part C: Written program", "text": "Read two numbers and print their sum.", "code": "",
     "marks": 3, "parts": [
        {"pid": "a", "prompt": "Write the program.", "marks": 3, "kind": "code", "lines": 10, "run": True,
         "stdin": True, "starter": KEYBOARD_STARTER}]}]}


class OldWindowTests(t28.Window):
    """Every 0028 window test, run against the 0030 window."""

    def setUp(self):
        super().setUp()
        self.old_window, t28.WINDOW = t28.WINDOW, WINDOW

    def tearDown(self):
        t28.WINDOW = self.old_window
        super().tearDown()


class Choices(OldWindowTests):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.run_dir, self.sitting, f"{self.user}.json"), "w") as handle:
            json.dump({"sitting": self.sitting, "title": "Made-up Test", "total": 5.0, "account": self.user,
                       **CHOICE_VERSION}, handle)

    # the 0028 tests use the 0028 made-up quiz; this class only runs its own
    def test_starter_reset_and_run(self):
        pass

    def test_run_shows_compile_problems(self):
        pass

    def test_saved_answers_come_back_after_a_crash(self):
        pass

    def test_hand_in_after_countdown(self):
        pass

    def test_buttons_choose_switch_and_clear(self):
        shown = self.window({"first": "Sam", "last": "Lee",
                             "choose": {"q1.1": "T", "q1.2": ["T", "F"], "q2.1": ["c", "b"]}})
        self.assertEqual(shown["answers"]["q1.1"], "T")
        self.assertEqual(shown["answers"]["q1.2"], "F")                       # switched: only F pressed
        self.assertEqual(shown["pressed"], {"q1.1": ["T"], "q1.2": ["F"], "q2.1": ["b"]})
        self.assertEqual(self.saved()["answers"]["q2.1"], "b")
        self.assertEqual(shown["sidebar"][:2], ["✓ Part A: True/False  ·  1 mark", "✓ Part A: Multiple choice  ·  1 mark"])
        self.assertIn("/5", shown["who"])
        shown = self.window({"choose": {"q1.1": "T"}})                         # pressing it again clears it
        self.assertEqual((shown["answers"]["q1.1"], shown["pressed"]["q1.1"]), ("", []))
        self.assertTrue(shown["sidebar"][0].startswith("○"))

    def test_choices_come_back_after_a_crash(self):
        self.window({"first": "Sam", "last": "Lee", "choose": {"q1.2": "F", "q2.1": "d"}})
        shown = self.window({})
        self.assertEqual(shown["pressed"]["q1.2"], ["F"])
        self.assertEqual(shown["pressed"]["q2.1"], ["d"])
        self.assertEqual(shown["pressed"]["q1.1"], [])

    def test_run_with_input_box(self):
        shown = self.window({"first": "Sam", "last": "Lee", "answers": {"q3.a": SUM_PROGRAM},
                             "input": {"q3.a": "2 65"}, "run": "q3.a"})
        self.assertEqual(shown["inputs"], ["q3.a"])
        self.assertEqual(shown["run_output"]["q3.a"].strip(), "Sum: 67")
        shown = self.window({"run": "q3.a"})                                   # Input box left empty
        self.assertIn("type the values in the Input box", shown["run_output"]["q3.a"])
        shown = self.window({"input": {"q3.a": "two 3"}, "run": "q3.a"})
        self.assertIn("isn't the kind of value", shown["run_output"]["q3.a"])


class InstallScript(unittest.TestCase):
    def test_install_script(self):
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read()
        self.assertIn("files/usr/local/lib/lab-quiz/quiz-window.py", script)
        self.assertIn("source \"$LAB_UPDATER_HELPERS\"", script)
        self.assertNotIn("lab-quiz-agent.py", script)                         # the agent is unchanged
        subprocess.run(["bash", "-n", os.path.join(UPDATE, "install.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
