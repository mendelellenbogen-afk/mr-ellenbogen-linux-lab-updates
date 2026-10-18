#!/usr/bin/env python3
"""Tests for 0024-class-polls: poll and close messages (listener), the answer
drop folder, signed + encrypted answers (laptop -> tools/lab-poll), counting,
the MCP server, and the poll window (GTK, on a private Broadway display when
gtk4-broadwayd is installed). The 0008-0023 live-message rules are rerun on
the new listener. Throwaway keys and folders; no network, no root.

    python3 -I update-repo/tests/test_0024_class_polls.py
"""

import io
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "updates", "0024-class-polls", "files")
LISTENER = os.path.join(FILES, "usr", "local", "lib", "lab-messages", "lab-messages-listener.py")
WINDOW = os.path.join(FILES, "usr", "local", "lib", "lab-messages", "poll-window.py")
CONFIG = os.path.join(FILES, "etc", "lab-messages", "config")
LAB_POLL = os.path.join(HERE, "..", "..", "tools", "lab-poll")

sys.path.insert(0, HERE)
import test_0008_live_messages as t8   # noqa: E402
import test_0019_admin_only_messages as t19   # noqa: E402
import test_0020_open_links as t20   # noqa: E402
import test_0021_fullscreen_links as t21   # noqa: E402
import test_0023_targeted_messages as t23   # noqa: E402

listener = t19.load("listener24", LISTENER)
for module in (t8, t19, t20, t21, t23):
    module.listener = listener

POLL_TOPIC = "poll-topic"
ME = pwd.getpwuid(os.getuid()).pw_name


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


class Config(unittest.TestCase):

    def test_poll_topics_are_new_and_distinct(self):
        saved = listener.CONFIG_FILE
        listener.CONFIG_FILE = CONFIG
        try:
            server, topic, admin, target = listener.read_config()
            poll, answers = listener.read_poll_config()
        finally:
            listener.CONFIG_FILE = saved
        self.assertTrue(poll and answers)
        self.assertEqual(len({topic, admin, target, poll, answers}), 5)


class PollMessages(t19.AdminOnly):
    """Poll and close messages, signed with the test lab key."""

    def setUp(self):
        super().setUp()
        with listener.POLLS_LOCK:
            listener.POLLS.clear()

    def signed(self, message_id, **fields):
        payload = dict({"v": 1, "id": message_id, "sent": t19.NOW, "title": "Class poll"}, **fields)
        text = json.dumps(payload)
        path = os.path.join(self.dir, "p-" + message_id)
        with open(path, "w") as handle:
            handle.write(text)
        if os.path.exists(path + ".sig"):
            os.unlink(path + ".sig")
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", os.path.join(self.dir, "teacher"),
                        "-n", "lab-message", path], check=True)
        with open(path + ".sig") as handle:
            return json.dumps({"payload": text, "sig": handle.read()})

    def deliver(self, *events):
        saved = listener.listen_once

        def listen_once(server, topics, admin_topic, since, seen, on_event_id, target_topic=""):
            return saved(server, topics, admin_topic, since, seen, on_event_id, "", POLL_TOPIC)
        listener.listen_once = listen_once
        try:
            return super().deliver(*events)
        finally:
            listener.listen_once = saved

    def poll(self, poll_id="p1", options=("for", "while", "do-while")):
        return {"id": poll_id, "question": "Which loop runs at least once?", "options": list(options)}

    def poll_file(self, poll_id="p1"):
        with open(os.path.join(listener.RUN_DIR, f"poll-{poll_id}.json")) as handle:
            return json.load(handle)

    def test_poll_opens_the_window_for_everyone(self):
        self.deliver((POLL_TOPIC, self.signed("m1", poll=self.poll())))
        self.assertEqual(self.windows, ["administrator", "studenttest1", "tdsb-123456789"])
        data = self.poll_file()
        self.assertEqual(data["options"], ["for", "while", "do-while"])
        self.assertFalse(data["closed"])
        self.assertFalse(listener.POLLS["p1"]["closed"])

    def test_poll_on_the_class_topic_is_ignored(self):
        # Older laptops listen there; a poll must never pop up as a plain message.
        self.deliver((t19.CLASS_TOPIC, self.signed("m2", poll=self.poll())))
        self.assertEqual(self.windows, [])
        self.assertNotIn("p1", listener.POLLS)

    def test_plain_message_on_the_poll_topic_is_ignored(self):
        self.deliver((POLL_TOPIC, self.signed("m3", text="hello")))
        self.assertEqual(self.windows, [])

    def test_unsigned_poll_is_ignored(self):
        body = json.dumps({"payload": json.dumps({"v": 1, "id": "m4", "sent": t19.NOW, "poll": self.poll()}),
                           "sig": "nope"})
        self.deliver((POLL_TOPIC, body))
        self.assertEqual(self.windows, [])

    def test_bad_polls_are_ignored(self):
        bad = [dict(self.poll(), options=["only one"]), dict(self.poll(), options=list("ABCDEFG")),
               dict(self.poll(), id="../etc"), dict(self.poll(), question=" "), "x",
               dict(self.poll(), options=["ok", 5])]
        for index, poll in enumerate(bad):
            self.deliver((POLL_TOPIC, self.signed(f"b{index}", poll=poll)))
        self.assertEqual(self.windows, [])

    def test_close_marks_results_and_reopens_windows(self):
        self.deliver((POLL_TOPIC, self.signed("m5", poll=self.poll())))
        self.windows.clear()
        close = dict(self.poll(), counts=[3, 1, 6], answered=10)
        self.deliver((POLL_TOPIC, self.signed("m6", poll_close=close)))
        self.assertEqual(len(self.windows), 3)
        data = self.poll_file()
        self.assertTrue(data["closed"])
        self.assertEqual(data["counts"], [3, 1, 6])
        self.assertTrue(listener.POLLS["p1"]["closed"])

    def test_close_for_a_poll_this_laptop_missed_still_shows_results(self):
        close = dict(self.poll("p9"), counts=[1, 0, 0], answered=1)
        self.deliver((POLL_TOPIC, self.signed("m7", poll_close=close)))
        self.assertEqual(len(self.windows), 3)
        self.assertTrue(self.poll_file("p9")["closed"])

    def test_bad_results_are_ignored(self):
        for index, close in enumerate([dict(self.poll(), counts=[1, 2], answered=3),
                                       dict(self.poll(), counts=[1, -2, 0], answered=3),
                                       dict(self.poll(), counts=[1, 2, 0], answered="3"),
                                       dict(self.poll(), counts=[True, 0, 0], answered=1)]):
            self.deliver((POLL_TOPIC, self.signed(f"c{index}", poll_close=close)))
        self.assertEqual(self.windows, [])


class Answers(unittest.TestCase):
    """The drop folder and the laptop's signed, encrypted answer."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.laptop_key = os.path.join(cls.dir, "laptop-key")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "lab-inventory",
                        "-f", cls.laptop_key], check=True)
        cls.teacher = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.teacher_pem = os.path.join(cls.dir, "teacher-key.pem")
        cls.teacher_pub = os.path.join(cls.dir, "teacher-key.pub.pem")
        with open(cls.teacher_pem, "wb") as handle:
            handle.write(cls.teacher.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
        with open(cls.teacher_pub, "wb") as handle:
            handle.write(cls.teacher.public_key().public_bytes(serialization.Encoding.PEM,
                                                               serialization.PublicFormat.SubjectPublicKeyInfo))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def setUp(self):
        self.saved = {name: getattr(listener, name) for name in
                      ("RUN_DIR", "LAPTOP_KEY", "TEACHER_KEY", "HOSTNAME")}
        listener.RUN_DIR = tempfile.mkdtemp(dir=self.dir)
        listener.LAPTOP_KEY, listener.TEACHER_KEY, listener.HOSTNAME = self.laptop_key, self.teacher_pub, "lab-a"
        listener.prepare_answer_dir()
        with listener.POLLS_LOCK:
            listener.POLLS.clear()
            listener.POLLS["p1"] = {"question": "Q", "options": ["a", "b", "c"], "closed": False,
                                    "started": time.time()}

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(listener, name, value)

    def drop(self, answer, name=None):
        path = os.path.join(listener.answer_dir(), name or f"{os.getuid()}-{os.urandom(4).hex()}.json")
        with open(path, "w") as handle:
            handle.write(answer if isinstance(answer, str) else json.dumps(answer))
        return path

    def test_drop_folder_is_sticky_and_world_writable(self):
        self.assertEqual(os.stat(listener.answer_dir()).st_mode & 0o7777, 0o1733)

    def test_last_answer_wins_and_account_comes_from_the_file_owner(self):
        first = self.drop({"poll": "p1", "choice": 0, "user": "someone-else"})
        os.utime(first, (time.time() - 5, time.time() - 5))
        self.drop({"poll": "p1", "choice": 2})
        pending = {}
        listener.collect_answers(pending)
        self.assertEqual(list(pending), [("p1", ME)])
        self.assertEqual(pending[("p1", ME)]["choice"], 2)
        self.assertEqual(pending[("p1", ME)]["laptop"], "lab-a")
        self.assertEqual(os.listdir(listener.answer_dir()), [])      # picked up and removed

    def test_bad_answers_are_dropped(self):
        self.drop({"poll": "p1", "choice": 3})
        self.drop({"poll": "p1", "choice": True})
        self.drop({"poll": "nope", "choice": 0})
        self.drop("not json")
        self.drop("x" * 2000)
        os.symlink("/etc/hostname", os.path.join(listener.answer_dir(), "link.json"))
        pending = {}
        listener.collect_answers(pending)
        self.assertEqual(pending, {})

    def test_no_answers_after_the_poll_closes(self):
        self.drop({"poll": "p1", "choice": 1})
        listener.POLLS["p1"]["closed"] = True
        pending = {}
        listener.collect_answers(pending)
        self.assertEqual(pending, {})

    def test_pending_answer_is_dropped_if_the_poll_closes_before_sending(self):
        pending = {("p1", ME): {"poll": "p1"}}
        listener.POLLS["p1"]["closed"] = True
        listener.send_answers("https://ntfy.example", "answers", pending)
        self.assertEqual(pending, {})

    def test_failed_send_is_kept_for_the_next_round(self):
        self.drop({"poll": "p1", "choice": 1})
        pending = {}
        listener.collect_answers(pending)
        saved = listener.urllib.request.urlopen
        listener.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
        try:
            listener.send_answers("https://ntfy.example", "answers", pending)
        finally:
            listener.urllib.request.urlopen = saved
        self.assertIn(("p1", ME), pending)

    def body_for(self, choice=1, user="tdsb-123456789", laptop="lab-a", poll="p1", sent=None):
        return listener.answer_body({"v": 1, "poll": poll, "choice": choice, "user": user,
                                     "laptop": laptop, "sent": sent or int(time.time())})

    @unittest.skipUnless(os.path.exists(LAB_POLL), "tools/lab-poll is only on the teacher's computer")
    def test_teacher_reads_and_counts_genuine_answers_only(self):
        lab_poll = t19.load("lab_poll", LAB_POLL)
        with open(self.laptop_key + ".pub") as handle:
            public = handle.read().strip()
        inventory = os.path.join(self.dir, "inventory.json")
        with open(inventory, "w") as handle:
            json.dump({"SER1": {"pubkey": public, "report": {"name": "lab-a"}},
                       "SER2": {"pubkey": "ssh-ed25519 AAAAother", "report": {"name": "lab-b"}}}, handle)
        lab_poll.INVENTORY = inventory
        store = lab_poll.Store(tempfile.mkdtemp(dir=self.dir))
        store.create({"id": "p1", "question": "Q", "options": ["a", "b", "c"], "started": int(time.time()),
                      "closed_at": None, "answers": {}, "ignored": 0, "seen_events": []})
        keys = lab_poll.known_keys()
        now = int(time.time())
        events = [
            {"id": "e1", "time": now, "message": self.body_for(choice=0, sent=now - 3)},
            {"id": "e2", "time": now, "message": self.body_for(choice=2, sent=now)},       # changed mind
            {"id": "e2", "time": now, "message": self.body_for(choice=0, sent=now + 1)},   # repeat event id
            {"id": "e3", "time": now, "message": self.body_for(choice=1, user="tdsb-555")},
            {"id": "e4", "time": now, "message": self.body_for(choice=1, laptop="lab-b")},  # wrong key
            {"id": "e5", "time": now, "message": "garbage"},
            {"id": "e6", "time": now, "message": self.body_for(choice=7)},                 # no such option
        ]
        for event in events:
            lab_poll.record(store, event, self.teacher, keys)
        poll = store.get()
        self.assertEqual(lab_poll.summarize(poll), {"counts": [0, 1, 1], "answered": 2})
        self.assertEqual(poll["ignored"], 3)
        public_view = json.dumps(lab_poll.public_results(poll))
        self.assertNotIn("tdsb-", public_view)
        self.assertNotIn("lab-a", public_view)
        self.assertEqual(lab_poll.public_results(poll)["counts"], [0, 1, 1])

        # Answers that arrive after the poll closed don't count.
        store.update("p1", lambda p: p.update(closed_at=now - 1))
        lab_poll.record(store, {"id": "e7", "time": now, "message": self.body_for(user="tdsb-777")},
                        self.teacher, keys)
        self.assertEqual(lab_poll.summarize(store.get())["answered"], 2)


@unittest.skipUnless(os.path.exists(LAB_POLL), "tools/lab-poll is only on the teacher's computer")
class TeacherTool(PollMessages):
    """tools/lab-poll's messages, opened by the real listener; and its MCP server."""

    def setUp(self):
        super().setUp()
        self.lab_poll = t19.load("lab_poll_t", LAB_POLL)
        self.store = self.lab_poll.Store(tempfile.mkdtemp(dir=self.dir))
        self.sent = []

        def fake_publish(payload, dry_run=False, sign=None):
            self.sent.append(payload)
        self.lab_poll.publish = fake_publish
        self.lab_poll.catch_up = lambda store, key=None: None

    def deliver_sent(self):
        for payload in self.sent:
            payload["sent"] = t19.NOW
            self.deliver((POLL_TOPIC, self.signed(payload["id"], **{k: v for k, v in payload.items()
                                                                   if k not in ("v", "id", "sent")})))
        self.sent.clear()

    def test_start_and_close_reach_the_laptops(self):
        poll, _ = self.lab_poll.start(self.store, " Best loop? ", ["for", " ", "while"])
        self.assertEqual(poll["options"], ["for", "while"])
        self.deliver_sent()
        self.assertEqual(len(self.windows), 3)
        self.store.update(poll["id"], lambda p: p["answers"].update(
            {"lab-a|tdsb-1": {"choice": 1, "sent": 1, "laptop": "lab-a", "user": "tdsb-1"}}))
        self.windows.clear()
        self.lab_poll.close(self.store)
        self.deliver_sent()
        self.assertEqual(len(self.windows), 3)
        data = self.poll_file(poll["id"])
        self.assertEqual((data["closed"], data["counts"], data["answered"]), (True, [0, 1], 1))

    def test_a_new_poll_closes_the_open_one(self):
        first, _ = self.lab_poll.start(self.store, "One?", ["a", "b"])
        self.lab_poll.start(self.store, "Two?", ["a", "b"])
        self.assertIn("poll_close", self.sent[1])
        self.assertTrue(self.store.get(first["id"])["closed_at"])

    def test_bad_polls_are_refused_before_sending(self):
        for question, options in (("", ["a", "b"]), ("Q", ["a"]), ("Q", list("abcdefg")), ("Q" * 501, ["a", "b"])):
            with self.assertRaises(ValueError):
                self.lab_poll.start(self.store, question, options)
        self.assertEqual(self.sent, [])

    def mcp(self, *requests):
        out = io.StringIO()
        self.lab_poll.serve_mcp(self.store, io.StringIO("".join(json.dumps(r) + "\n" for r in requests)),
                                out, listen=False)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_mcp_server(self):
        replies = self.mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "poll_results", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "start_poll", "arguments": {"question": "Q?", "options": ["x", "y"]}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "start_poll", "arguments": {"question": "Q?", "options": ["x"]}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "close_poll", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "nope"},
        )
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "lab-poll")
        self.assertEqual({t["name"] for t in replies[1]["result"]["tools"]},
                         {"poll_results", "start_poll", "resend_poll", "close_poll"})
        self.assertEqual(replies[2]["result"]["structuredContent"], {"poll": None})
        started = replies[3]["result"]["structuredContent"]
        self.assertEqual((started["poll"]["question"], started["poll"]["open"], started["counts"]), ("Q?", True, [0, 0]))
        self.assertTrue(replies[4]["result"]["isError"])
        self.assertIn("2 to 6", replies[4]["result"]["content"][0]["text"])
        self.assertFalse(replies[5]["result"]["structuredContent"]["poll"]["open"])
        self.assertIn("error", replies[6])


@unittest.skipUnless(shutil.which("gtk4-broadwayd"), "needs gtk4-broadwayd for a private display")
class Window(unittest.TestCase):
    """The real GTK window on a private Broadway display (never the user's screen)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.display = f":{40 + os.getpid() % 50}"
        cls.runtime = os.path.join(cls.dir, "runtime")     # broadwayd's socket lives here
        os.makedirs(cls.runtime, mode=0o700)
        cls.broadway = subprocess.Popen(["gtk4-broadwayd", cls.display], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, env=dict(os.environ, XDG_RUNTIME_DIR=cls.runtime))
        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        cls.broadway.terminate()
        cls.broadway.wait()
        shutil.rmtree(cls.dir)

    def run_window(self, poll, choice, close_after=None):
        path = os.path.join(self.dir, f"poll-{poll['id']}.json")
        with open(path, "w") as handle:
            json.dump(poll, handle)
        answers = os.path.join(self.dir, "answers-" + poll["id"])
        os.makedirs(answers, exist_ok=True)
        env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=self.display, LAB_POLL_ANSWER_DIR=answers,
                   LAB_POLL_APP_ID="com.school.LabPollTest" + poll["id"], LAB_POLL_SELFTEST=str(choice),
                   LAB_MESSAGE_TIMEOUT="20", XDG_RUNTIME_DIR=self.runtime)
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        window = subprocess.Popen(["python3", "-I", WINDOW, path], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        if close_after:
            time.sleep(close_after)
            counts = [1, 3, 0][:len(poll["options"])]
            with open(path, "w") as handle:
                json.dump(dict(poll, closed=True, counts=counts, answered=4), handle)
        out, err = window.communicate(timeout=30)
        return out, err, answers

    def test_pick_then_results(self):
        poll = {"id": "pw1", "question": "Which loop?", "options": ["for", "while", "do-while"], "closed": False}
        out, err, answers = self.run_window(poll, 1, close_after=3)
        self.assertIn("STATUS:Answer sent: B.", out, err)
        self.assertIn("CLOSABLE:True", out)
        self.assertIn("RESULTS:The poll is closed. 4 answered.", out)
        self.assertIn("ROW:B.  while   3 (75%)   ← your answer", out)
        dropped = []
        for name in os.listdir(answers):
            with open(os.path.join(answers, name)) as handle:
                dropped.append(json.load(handle))
        self.assertEqual(dropped, [{"poll": "pw1", "choice": 1}])

    def test_cannot_close_before_answering(self):
        poll = {"id": "pw3", "question": "Q?", "options": ["a", "b"], "closed": False}
        out, err, answers = self.run_window(poll, -1, close_after=3)
        self.assertIn("STATUS:Pick one answer.", out, err)
        self.assertIn("CLOSABLE:False", out)
        self.assertIn("RESULTS:The poll is closed. 4 answered.", out)
        self.assertEqual(os.listdir(answers), [])

    def test_closed_poll_shows_results(self):
        poll = {"id": "pw2", "question": "Q?", "options": ["a", "b", "c"], "closed": True,
                "counts": [2, 0, 0], "answered": 2}
        out, err, answers = self.run_window(poll, 0)
        self.assertIn("RESULTS:The poll is closed. 2 answered.", out, err)
        self.assertIn("ROW:A.  a   2 (100%)", out)
        self.assertEqual(os.listdir(answers), [])     # nothing to answer once it is closed


if __name__ == "__main__":
    unittest.main(verbosity=1)
