#!/usr/bin/env python3
"""Tests for 0025-poll-correct-answers: optional correct answers (one or more)
travel only with the results; each laptop says "Correct!" or "Not quite".
All 0024 poll tests (and through them 0008-0023) rerun on the new files.
No network, no root.

    python3 -I update-repo/tests/test_0025_poll_correct_answers.py
"""

import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "updates", "0025-poll-correct-answers", "files", "usr", "local", "lib", "lab-messages")
LISTENER = os.path.join(FILES, "lab-messages-listener.py")
WINDOW = os.path.join(FILES, "poll-window.py")

sys.path.insert(0, HERE)
import test_0008_live_messages as t8   # noqa: E402
import test_0019_admin_only_messages as t19   # noqa: E402
import test_0020_open_links as t20   # noqa: E402
import test_0021_fullscreen_links as t21   # noqa: E402
import test_0023_targeted_messages as t23   # noqa: E402
import test_0024_class_polls as t24   # noqa: E402

listener = t19.load("listener25", LISTENER)
for module in (t8, t19, t20, t21, t23, t24):
    module.listener = listener
t24.WINDOW = WINDOW


class Old0008(t8.LiveMessages):
    pass


class Old0019(t19.AdminOnly):
    pass


class Old0020(t20.OpenLinks):
    pass


class Old0021Routing(t21.Routing):
    pass


class Old0023Targeted(t23.Targeted):
    pass


class Old0024Polls(t24.PollMessages):
    pass


class Old0024Answers(t24.Answers):
    pass


class Old0024Teacher(t24.TeacherTool):
    pass


class Old0024Window(t24.Window):
    pass


class CorrectOnLaptop(t24.PollMessages):

    def close(self, message_id, **extra):
        close = dict(self.poll(), counts=[3, 1, 6], answered=10, **extra)
        self.deliver((t24.POLL_TOPIC, self.signed(message_id, poll_close=close)))

    def test_correct_answers_reach_the_poll_file(self):
        self.close("k1", correct=[2, 0])
        self.assertEqual(self.poll_file()["correct"], [0, 2])

    def test_opinion_poll_has_no_correct_answers(self):
        self.close("k2")
        self.assertEqual(self.poll_file()["correct"], [])

    def test_bad_correct_answers_are_ignored(self):
        for index, correct in enumerate([[3], [-1], [1, 1], [True], "2", [1.0]]):
            self.close(f"k3{index}", correct=correct)
        self.assertEqual(self.windows, [])

    def test_poll_payload_with_correct_answers_still_works(self):
        # The teacher never sends them with the poll, but a stray field must not break it.
        self.deliver((t24.POLL_TOPIC, self.signed("k4", poll=dict(self.poll(), correct=[1]))))
        self.assertEqual(len(self.windows), 3)
        self.assertNotIn("correct", self.poll_file())


@unittest.skipUnless(os.path.exists(t24.LAB_POLL), "tools/lab-poll is only on the teacher's computer")
class CorrectOnTeacher(t24.TeacherTool):

    def test_letters_and_numbers(self):
        clean = self.lab_poll.clean_correct
        self.assertEqual(clean(["b,C"], ["x", "y", "z"]), [1, 2])
        self.assertEqual(clean(["a", "A", 2], ["x", "y", "z"]), [0, 2])
        self.assertEqual(clean([], ["x", "y"]), [])
        for bad in (["D"], ["7"], [5], ["xy"], [True]):
            with self.assertRaises(ValueError):
                clean(bad, ["x", "y", "z"])

    def test_secret_until_closed(self):
        poll, _ = self.lab_poll.start(self.store, "Q?", ["x", "y", "z"], correct=["B", "C"])
        self.assertNotIn("correct", json.dumps(self.sent[0]))          # not in the poll message
        self.store.update(poll["id"], lambda p: p["answers"].update({
            "lab-a|tdsb-1": {"choice": 1, "sent": 1, "laptop": "lab-a", "user": "tdsb-1"},
            "lab-b|tdsb-2": {"choice": 0, "sent": 1, "laptop": "lab-b", "user": "tdsb-2"},
            "lab-c|tdsb-3": {"choice": 2, "sent": 1, "laptop": "lab-c", "user": "tdsb-3"}}))
        open_view = self.lab_poll.public_results(self.store.get())
        self.assertTrue(open_view["poll"]["quiz"])
        self.assertNotIn("correct", open_view)                          # the board is projected
        self.assertNotIn("right", open_view)
        self.windows.clear()
        self.lab_poll.close(self.store)
        self.assertEqual(self.sent[-1]["poll_close"]["correct"], [1, 2])
        self.deliver_sent()
        self.assertEqual(self.poll_file(poll["id"])["correct"], [1, 2])
        closed_view = self.lab_poll.public_results(self.store.get())
        self.assertEqual((closed_view["correct"], closed_view["right"]), ([1, 2], 2))

    def test_opinion_poll_close_has_no_correct(self):
        self.lab_poll.start(self.store, "Q?", ["x", "y"])
        self.lab_poll.close(self.store)
        self.assertNotIn("correct", self.sent[-1]["poll_close"])
        view = self.lab_poll.public_results(self.store.get())
        self.assertFalse(view["poll"]["quiz"])
        self.assertNotIn("correct", view)

    def test_mcp_start_with_correct(self):
        replies = self.mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "start_poll", "arguments": {"question": "Q?", "options": ["x", "y"], "correct": [1]}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "start_poll", "arguments": {"question": "Q?", "options": ["x", "y"], "correct": [4]}}})
        self.assertTrue(replies[0]["result"]["structuredContent"]["poll"]["quiz"])
        self.assertTrue(replies[1]["result"]["isError"])


class CorrectWindow(t24.Window):

    def closed_poll(self, poll_id, correct):
        return {"id": poll_id, "question": "Q?", "options": ["a", "b", "c"], "closed": False, "correct": correct}

    def test_correct(self):
        out, err, _ = self.run_window(self.closed_poll("pc1", [1]), 1, close_after=3)
        self.assertIn("VERDICT:Correct!", out, err)
        self.assertIn("ROW:✓ B.  b", out)

    def test_not_quite_with_two_correct_answers(self):
        out, err, _ = self.run_window(self.closed_poll("pc2", [1, 2]), 0, close_after=3)
        self.assertIn("VERDICT:Not quite: the answer was B or C.", out, err)

    def test_no_answer_just_shows_it(self):
        out, err, _ = self.run_window(self.closed_poll("pc3", [2]), -1, close_after=3)
        self.assertIn("VERDICT:The answer was C.", out, err)

    def test_opinion_poll_has_no_verdict(self):
        out, err, _ = self.run_window(self.closed_poll("pc4", []), 0, close_after=3)
        self.assertIn("RESULTS:", out, err)
        self.assertNotIn("VERDICT:", out)

    def run_window(self, poll, choice, close_after=None):
        # The 0024 helper writes closed=True, counts, answered; keep "correct".
        saved = json.dump

        def dump(data, handle, **kwargs):
            if data.get("closed") and "correct" not in data:
                data = dict(data, correct=poll.get("correct", []))
            return saved(data, handle, **kwargs)
        t24.json.dump = dump
        try:
            return super().run_window(poll, choice, close_after)
        finally:
            t24.json.dump = saved


if __name__ == "__main__":
    unittest.main(verbosity=1)
