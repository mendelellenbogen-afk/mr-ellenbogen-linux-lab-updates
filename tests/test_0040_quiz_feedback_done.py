#!/usr/bin/env python3
"""Tests for 0040-quiz-feedback-done: a student looking at their marks (0039)
can press "I'm done": the agent ends exam mode for that student only and says
"over", and the window closes. Every 0039 test (and the older agent/window
tests it reruns) reruns on the new files.
Fakes only: no network, no root, no real firewall (Java runs for the grader).

    python3 -I update-repo/tests/test_0040_quiz_feedback_done.py
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0040-quiz-feedback-done")
LIB = os.path.join(UPDATE, "files", "usr", "local", "lib", "lab-quiz")
AGENT = os.path.join(LIB, "lab-quiz-agent.py")
WINDOW = os.path.join(LIB, "quiz-window.py")

sys.path.insert(0, HERE)
import test_0028_quiz_improvements_power as t28   # noqa: E402
import test_0030_quiz_choices_input as t30   # noqa: E402
import test_0039_quiz_feedback as t39   # noqa: E402

t28.AGENT = AGENT
t28.WINDOW = WINDOW
t30.WINDOW = WINDOW
t39.AGENT = AGENT
t39.WINDOW = WINDOW


# ---------------------------------------------------------------- older tests on the new files

class Old0028Agent(t39.Old0028Agent):
    pass


class Old0028Window(t39.Old0028Window):
    pass


class Old0030Choices(t39.Old0030Choices):
    pass


class Old0036Countdown(t39.Old0036Countdown):
    pass


class Old0036WindowSounds(t39.Old0036WindowSounds):
    pass


class Old0038AgentServers(t39.Old0038AgentServers):
    pass


class Old0039Grader(t39.Grader):
    pass


class Old0039Feedback(t39.Feedback):
    pass


class Old0039ReviewWindow(t39.ReviewWindow):
    def test_marks_shown_but_not_closable_before_the_end(self):
        """0040: before the end the top button is "I'm done", not Close."""
        shown = self.review(self.FEEDBACK, {"q1.a": "3"}, over=False)
        self.assertIsNotNone(shown["review"])
        self.assertIn("When you're done, press", shown["review"])
        self.assertFalse(shown["over"])
        self.assertTrue(shown["close_visible"])
        self.assertEqual(shown["close_label"], "I'm done — close the quiz")


# ---------------------------------------------------------------- "I'm done"

class Done(t39.Feedback):
    def drop(self, sitting, done=True):
        with open(os.path.join(self.dir, "run", "submit", "d.json"), "w") as handle:
            json.dump({"sitting": sitting, "done": done}, handle)

    def test_done_ends_exam_mode_for_that_student(self):
        sitting, record = self.start_with_feedback()
        laptop = self.agent.Laptop("https://ntfy.sh")
        self.tick(laptop)
        self.save_answers(sitting, {"q1.a": "1"})
        self.hand_in_now(sitting)
        self.tick(laptop)
        self.wait_feedback(sitting)
        self.tick(laptop)
        self.assertTrue(laptop.locked)
        self.drop(sitting)
        self.tick(laptop)
        self.assertEqual(self.status(sitting), {"state": "handed", "feedback": True, "over": True})
        self.assertFalse(laptop.locked)
        self.assertTrue(os.path.exists(self.agent.done_path(sitting, "tdsb-111")))
        opened = self.calls().count("--unit=")
        self.tick(laptop, 3)
        self.assertEqual(self.calls().count("--unit="), opened)       # the window isn't reopened

    def test_done_before_hand_in_is_ignored(self):
        sitting, record = self.start_with_feedback()
        laptop = self.agent.Laptop("https://ntfy.sh")
        self.tick(laptop)
        self.drop(sitting)
        self.tick(laptop)
        self.assertEqual(self.status(sitting), {"state": "open"})       # still writing
        self.assertFalse(os.path.exists(self.agent.done_path(sitting, "tdsb-111")))
        self.assertTrue(laptop.locked)
        self.drop(sitting, done="yes")                                   # only true counts
        self.tick(laptop)
        self.assertEqual(self.status(sitting), {"state": "open"})

    def test_a_plain_drop_still_hands_in(self):
        sitting, record = self.start_with_feedback()
        laptop = self.agent.Laptop("https://ntfy.sh")
        self.tick(laptop)
        self.save_answers(sitting, {"q1.a": "1"})
        self.hand_in_now(sitting)
        self.tick(laptop)
        self.assertTrue(self.agent.handed_in(sitting, "tdsb-111"))


class DoneWindow(Old0039ReviewWindow):
    def test_im_done_asks_the_agent_then_closes(self):
        import subprocess
        import time
        env = dict(os.environ, HOME=self.home, LAB_QUIZ_COUNTDOWN="1", GDK_BACKEND="broadway",
                   BROADWAY_DISPLAY=self.display, XDG_RUNTIME_DIR=self.runtime, LAB_QUIZ_RUN=self.run_dir,
                   LAB_QUIZ_WINDOWED="1", LAB_QUIZ_APP_ID=f"com.school.LabQuizTest{os.getpid()}{int(time.time() * 1000) % 100000}",
                   LAB_QUIZ_SELFTEST=json.dumps({"first": "Sam", "last": "Lee", "answers": {"q1.a": "3"},
                                                 "handin": "HAND IN", "wait_review": True, "done": True}))
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
        for name in os.listdir(submit):                                  # the hand-in
            os.unlink(os.path.join(submit, name))
        with open(os.path.join(self.run_dir, self.sitting, f"{self.user}.feedback"), "w") as handle:
            json.dump(self.FEEDBACK, handle)
        with open(status, "w") as handle:
            json.dump({"state": "handed", "feedback": True}, handle)
        drops = []
        for _ in range(100):                                             # then "I'm done"
            drops = os.listdir(submit)
            if drops:
                break
            time.sleep(0.2)
        self.assertEqual(len(drops), 1)
        with open(os.path.join(submit, drops[0])) as handle:
            self.assertEqual(json.load(handle), {"sitting": self.sitting, "done": True})
        with open(status, "w") as handle:
            json.dump({"state": "handed", "feedback": True, "over": True}, handle)
        out, err = process.communicate(timeout=90)
        self.assertEqual(process.returncode, 0, err)
        shown = json.loads(out.strip().splitlines()[-1])
        self.assertTrue(shown["leaving"])
        self.assertTrue(shown["left"])
        self.assertEqual(shown["close_label"], "Closing…")


class InstallScript(unittest.TestCase):
    def test_installs_every_file_it_ships(self):
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read()
        shipped = sorted(os.path.relpath(os.path.join(root, name), os.path.join(UPDATE, "files"))
                         for root, _dirs, names in os.walk(os.path.join(UPDATE, "files")) for name in names
                         if "__pycache__" not in root)
        self.assertEqual(len(shipped), 2)
        for path in shipped:
            self.assertIn(f"files/{path}", script)
        self.assertIn("systemctl restart lab-quiz.service", script)

    def test_programs_compile(self):
        for path in (AGENT, WINDOW):
            with open(path) as handle:
                compile(handle.read(), path, "exec")


if __name__ == "__main__":
    unittest.main()
