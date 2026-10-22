#!/usr/bin/env python3
"""Tests for 0038-lab-message-server: the listener, the quiz agent and the
inventory report use PRIMARY_SERVER (the lab's own ntfy) first and ntfy.sh as
the fallback, go back to the lab server when it answers again, handle a
message that arrives from both servers once, send to the first server that
takes it, take the quiz file from a mirror, and let the quiz firewall reach
both servers. Every older listener (0008-0025, 0036), quiz agent (0028, 0036)
and inventory report (0022, 0029) test reruns on the new files.
Fakes only: no network, no root, no real firewall.

    python3 -I update-repo/tests/test_0038_lab_message_server.py
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATES = os.path.join(HERE, "..", "updates")
UPDATE = os.path.join(UPDATES, "0038-lab-message-server")
FILES = os.path.join(UPDATE, "files")
LISTENER = os.path.join(FILES, "usr", "local", "lib", "lab-messages", "lab-messages-listener.py")
AGENT = os.path.join(FILES, "usr", "local", "lib", "lab-quiz", "lab-quiz-agent.py")
REPORTER = os.path.join(FILES, "usr", "local", "lib", "lab-inventory", "lab-inventory-report")
CONFIGS = {  # new config -> the one it replaces
    "etc/lab-messages/config": "0024-class-polls",
    "etc/lab-quiz/config": "0027-exam-mode",
    "etc/lab-inventory/config": "0029-taken-home",
}
LAB = "https://lab-messages.example.ts.net"
NTFY = "https://ntfy.sh"

sys.path.insert(0, HERE)
import test_0008_live_messages as t8   # noqa: E402
import test_0019_admin_only_messages as t19   # noqa: E402
import test_0020_open_links as t20   # noqa: E402
import test_0021_fullscreen_links as t21   # noqa: E402
import test_0022_lab_inventory as t22   # noqa: E402
import test_0023_targeted_messages as t23   # noqa: E402
import test_0024_class_polls as t24   # noqa: E402
import test_0025_poll_correct_answers as t25   # noqa: E402
import test_0028_quiz_improvements_power as t28   # noqa: E402
import test_0029_taken_home as t29   # noqa: E402
import test_0036_lab_sounds as t36   # noqa: E402

listener = t19.load("listener38", LISTENER)
for module in (t8, t19, t20, t21, t23, t24, t25, t36):
    module.listener = listener
t24.WINDOW = t25.WINDOW
t28.AGENT = AGENT
t22.rep = t22.load("reporter38a", REPORTER)
t29.rep = t29.load("reporter38b", REPORTER)


# ---------------------------------------------------------------- older tests on the new files

class Old0008(t8.LiveMessages):
    pass


class Old0019(t19.AdminOnly):
    pass


class Old0020(t20.OpenLinks):
    pass


class Old0021Routing(t21.Routing):
    pass


class Old0022Reporter(t22.Reporter):
    pass


class Old0023Targeted(t23.Targeted):
    pass


class Old0024Polls(t24.PollMessages):
    pass


class Old0025Laptop(t25.CorrectOnLaptop):
    pass


class Old0028Agent(t28.Agent):
    pass


class Old0029Reporter(t29.Reporter):
    pass


class Old0036Sounds(t36.SoundMessages):
    pass


class Old0036Countdown(t36.EndCountdown):
    pass


# ---------------------------------------------------------------- helpers

class Stream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def events(*bodies, start=0):
    lines = [json.dumps({"event": "open"}).encode()]
    for i, body in enumerate(bodies):
        lines.append(json.dumps({"event": "message", "id": f"e{start + i}", "time": t19.NOW,
                                 "topic": t19.CLASS_TOPIC, "message": body}).encode())
    return Stream(b"\n".join(lines) + b"\n")


class Stop(BaseException):
    """Ends a `while True` loop in a test (the programs only catch Exception)."""


# ---------------------------------------------------------------- configs

class Configs(unittest.TestCase):
    def read(self, path):
        with open(path) as handle:
            return handle.read()

    def test_only_primary_server_added(self):
        for new, old in CONFIGS.items():
            text = self.read(os.path.join(FILES, new))
            kept = [line for line in text.splitlines()
                    if not line.startswith("PRIMARY_SERVER=") and "0038" not in line
                    and not line.startswith("# through Tailscale Funnel") and not line.startswith("# when it can't")
                    and not line.startswith("# these servers")]
            before = [line for line in self.read(os.path.join(UPDATES, old, "files", new)).splitlines()
                      if not line.startswith("# this SERVER.")]
            self.assertEqual(kept, before, new)

    def test_primary_server_is_https_and_the_same_everywhere(self):
        found = set()
        for new in CONFIGS:
            lines = [line for line in self.read(os.path.join(FILES, new)).splitlines()
                     if line.startswith("PRIMARY_SERVER=")]
            self.assertEqual(len(lines), 1, new)
            found.add(lines[0].split("=", 1)[1])
        self.assertEqual(len(found), 1)
        address = found.pop()
        self.assertRegex(address, r"^https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$")

    def test_primary_server_address_filled_in(self):
        """Fails until the teacher's server is set up and its address is in the configs."""
        for new in CONFIGS:
            self.assertNotIn("TAILNET", self.read(os.path.join(FILES, new)), new)

    def test_server_list_everywhere(self):
        reporter = t22.rep
        for read in (lambda cfg: listener.server_list(cfg), lambda cfg: agent_module().server_list(cfg)):
            self.assertEqual(read({"SERVER": NTFY, "PRIMARY_SERVER": LAB + "/"}), [LAB, NTFY])
            self.assertEqual(read({"SERVER": NTFY}), [NTFY])
            self.assertEqual(read({"SERVER": NTFY, "PRIMARY_SERVER": ""}), [NTFY])
            self.assertEqual(read({"SERVER": NTFY, "PRIMARY_SERVER": "http://plain.example"}), [NTFY])
            self.assertEqual(read({"SERVER": NTFY, "PRIMARY_SERVER": NTFY}), [NTFY])
        with tempfile.NamedTemporaryFile("w", suffix="config") as config:
            config.write(f"SERVER={NTFY}\nPRIMARY_SERVER={LAB}\nTOPIC=t\n")
            config.flush()
            with mock.patch.object(reporter, "CONFIG_FILE", config.name):
                self.assertEqual(reporter.read_config(), ([LAB, NTFY], "t"))

    def test_real_configs_read(self):
        with mock.patch.object(listener, "CONFIG_FILE", os.path.join(FILES, "etc/lab-messages/config")):
            servers, topic, admin, target = listener.read_config()
        self.assertEqual(len(servers), 2)
        self.assertEqual(servers[1], NTFY)
        self.assertTrue(topic and admin and target)


_AGENT = []


def agent_module():
    if not _AGENT:
        _AGENT.append(t28.load_agent())
    return _AGENT[0]


# ---------------------------------------------------------------- listener

class ListenerFailover(unittest.TestCase):
    """main(): lab server first, ntfy.sh when it fails, back when it answers."""

    def run_main(self, script, health):
        calls = []
        script = list(script)
        health = list(health)

        def fake_listen_once(server, topics, admin_topic, since, seen, remember, target, poll, until):
            calls.append((server, since, until))
            if not script:
                raise Stop()
            outcome = script.pop(0)
            if outcome == "fail":
                raise OSError("down")
            if outcome == "event":
                remember(1000)

        config = tempfile.NamedTemporaryFile("w", delete=False)
        config.write(f"SERVER={NTFY}\nPRIMARY_SERVER={LAB}\nTOPIC=t\n")
        config.close()
        self.addCleanup(os.unlink, config.name)
        with mock.patch.object(listener, "CONFIG_FILE", config.name), \
                mock.patch.object(listener, "listen_once", fake_listen_once), \
                mock.patch.object(listener, "healthy", lambda server: health.pop(0) if health else False), \
                mock.patch.object(listener.time, "sleep", lambda seconds: None), \
                mock.patch.object(listener, "log", lambda message: None):
            with self.assertRaises(Stop):
                listener.main()
        return calls

    def test_lab_server_first_and_stays_while_it_works(self):
        calls = self.run_main(["ok", "ok"], [])
        self.assertEqual([c[0] for c in calls], [LAB, LAB, LAB])
        self.assertIsNone(calls[0][2])                      # no time limit on the lab server

    def test_falls_back_then_goes_back_when_healthy(self):
        calls = self.run_main(["event", "fail", "ok", "ok"], [False, True])
        servers = [c[0] for c in calls]
        self.assertEqual(servers, [LAB, LAB, NTFY, NTFY, LAB])
        self.assertIsNotNone(calls[2][2])                   # on ntfy.sh: limited, to check the lab server again
        self.assertEqual(calls[2][1], 1000)                 # catch up from the last message seen
        self.assertEqual(calls[4][1], 1000)

    def test_catch_up_without_any_message_yet(self):
        calls = self.run_main(["fail"], [])
        self.assertEqual(calls[1][0], NTFY)
        self.assertIsInstance(calls[1][1], int)             # since = just before the drop

    def test_both_down_retries_lab_server(self):
        calls = self.run_main(["fail", "fail"], [False])
        self.assertEqual([c[0] for c in calls], [LAB, NTFY, LAB])


class ListenerTimeLimit(t19.AdminOnly):
    def test_until_stops_the_fallback_stream(self):
        with mock.patch.object(listener.urllib.request, "urlopen",
                               lambda request, timeout: events(self.body("m1"), self.body("m2"))):
            listener.listen_once(NTFY, [t19.CLASS_TOPIC], t19.ADMIN_TOPIC, None, set(), lambda t: None,
                                 until=0)
        self.assertEqual(self.windows, [])

    def test_same_message_from_both_servers_is_shown_once(self):
        body = self.body("m1")
        seen = set()
        for server, start in ((LAB, 0), (NTFY, 50)):
            with mock.patch.object(listener.urllib.request, "urlopen",
                                   lambda request, timeout, start=start: events(body, start=start)):
                listener.listen_once(server, [t19.CLASS_TOPIC], t19.ADMIN_TOPIC, None, seen, lambda t: None)
        self.assertEqual(self.windows, ["administrator", "studenttest1", "tdsb-123456789"])


class ListenerPost(unittest.TestCase):
    def test_first_server_that_takes_it(self):
        tried = []

        def fake(request, timeout):
            tried.append(request.full_url)
            if request.full_url.startswith(LAB):
                raise OSError("down")
            return Stream(b"{}")
        with mock.patch.object(listener.urllib.request, "urlopen", fake):
            self.assertEqual(listener.post([LAB, NTFY], "answers", b"x", "lab-poll/1"), NTFY)
            self.assertEqual(tried, [f"{LAB}/answers", f"{NTFY}/answers"])
            tried.clear()
            listener.post(NTFY, "answers", b"x", "lab-poll/1")          # one server as a string
            self.assertEqual(tried, [f"{NTFY}/answers"])

    def test_all_down_raises(self):
        def fake(request, timeout):
            raise OSError("down")
        with mock.patch.object(listener.urllib.request, "urlopen", fake):
            with self.assertRaises(OSError):
                listener.post([LAB, NTFY], "answers", b"x", "lab-poll/1")

    def test_healthy(self):
        with mock.patch.object(listener.urllib.request, "urlopen",
                               lambda request, timeout: Stream(b'{"healthy":true}')):
            self.assertTrue(listener.healthy(LAB))
        with mock.patch.object(listener.urllib.request, "urlopen",
                               lambda request, timeout: Stream(b'{"healthy":false}')):
            self.assertFalse(listener.healthy(LAB))

        def down(request, timeout):
            raise OSError("down")
        with mock.patch.object(listener.urllib.request, "urlopen", down):
            self.assertFalse(listener.healthy(LAB))


# ---------------------------------------------------------------- quiz agent

class AgentServers(t28.Agent):
    def test_listen_dedupes_and_falls_back(self):
        agent = self.agent
        handled, opened = [], []
        stop = threading.Event()
        bodies = ['{"payload": "a"}', '{"payload": "b"}']

        def fake(request, timeout):
            opened.append(request.full_url)
            if len(opened) == 1:
                raise OSError("lab server down")
            if len(opened) == 3:
                stop.set()
            return events(*bodies, start=len(opened) * 10)
        with mock.patch.object(agent.urllib.request, "urlopen", fake), \
                mock.patch.object(agent, "parse", lambda body: {"body": body}), \
                mock.patch.object(agent, "handle", lambda message: handled.append(message["body"])), \
                mock.patch.object(agent, "healthy", lambda server: False), \
                mock.patch.object(agent.time, "sleep", lambda seconds: None):
            agent.listen([LAB, NTFY], "quiz-topic", stop)
        self.assertTrue(opened[0].startswith(f"{LAB}/quiz-topic/json?since=5h"))
        self.assertTrue(opened[1].startswith(f"{NTFY}/quiz-topic/json?since=5h"))
        self.assertEqual(handled, bodies)                   # each message once, though fetched again

    def test_listen_goes_back_to_lab_server(self):
        agent = self.agent
        opened = []
        stop = threading.Event()

        def fake(request, timeout):
            opened.append(request.full_url.split("/quiz-topic")[0])
            if len(opened) == 1:
                raise OSError("down")
            if len(opened) == 3:
                stop.set()
            return events()
        with mock.patch.object(agent.urllib.request, "urlopen", fake), \
                mock.patch.object(agent, "PRIMARY_RETRY_SECONDS", -1), \
                mock.patch.object(agent, "healthy", lambda server: True), \
                mock.patch.object(agent.time, "sleep", lambda seconds: None):
            agent.listen([LAB, NTFY], "quiz-topic", stop)
        self.assertEqual(opened, [LAB, NTFY, LAB])

    def test_mirrors_first_then_url(self):
        agent = self.agent
        tried = []

        def fake_download(url, sha256, key):
            tried.append(url)
            if "mirror-bad" in url:
                raise ValueError("package doesn't match")
            return {"from": url}
        package = {"url": f"{NTFY}/file/a.bin", "sha256": "x", "key": "k",
                   "mirrors": [f"{LAB}/file/mirror-bad.bin", f"{LAB}/file/b.bin"]}
        with mock.patch.object(agent, "download", fake_download):
            self.assertEqual(agent.download_any(package), {"from": f"{LAB}/file/b.bin"})
            tried.clear()
            self.assertEqual(agent.download_any({"url": f"{NTFY}/file/a.bin", "sha256": "x", "key": "k"}),
                             {"from": f"{NTFY}/file/a.bin"})          # a start from before 0038

    def test_mirror_list(self):
        mirror_list = self.agent.mirror_list
        self.assertEqual(mirror_list(None), [])
        self.assertEqual(mirror_list("https://x"), [])
        self.assertEqual(mirror_list(["http://x", 5, "https://a", "file:///etc"]), ["https://a"])
        self.assertEqual(len(mirror_list([f"https://{n}" for n in range(9)])), self.agent.MAX_MIRRORS)

    def test_start_keeps_mirrors(self):
        agent = self.agent
        message = {"id": "m1", "sent": __import__("time").time(), "quiz_start": {
            "sitting": "made-up-20261022-1200", "title": "Made-up", "total": 5, "url": f"{NTFY}/file/a.bin",
            "sha256": "x", "key": "k", "mirrors": [f"{LAB}/file/a.bin", "http://plain/file"]}}
        with mock.patch.object(agent, "ensure_package", lambda record: False):
            agent.handle_start(message)
        record = agent.read_json(os.path.join(agent.sitting_dir("made-up-20261022-1200"), "start.json"))
        self.assertEqual(record["package"]["mirrors"], [f"{LAB}/file/a.bin"])
        self.assertEqual(record["package"]["url"], f"{NTFY}/file/a.bin")

    def test_firewall_allows_both_servers(self):
        agent = self.agent
        scripts = []
        hosts = {"lab-messages.example.ts.net": ({"198.51.100.7"}, set()),
                 "ntfy.sh": ({"203.0.113.5"}, {"2001:db8::5"})}
        with mock.patch.object(agent, "addresses", lambda host: hosts[host]), \
                mock.patch.object(agent, "nft", lambda script: scripts.append(script) or
                                  subprocess.CompletedProcess([], 0, "", "")):
            laptop = agent.Laptop([LAB, NTFY])
            self.assertEqual(laptop.server_hosts, ["lab-messages.example.ts.net", "ntfy.sh"])
            self.assertTrue(agent.firewall_on(laptop.server_hosts, laptop.known))
        self.assertIn("198.51.100.7, 203.0.113.5", scripts[0])
        self.assertIn("2001:db8::5", scripts[0])

    def test_laptop_takes_one_server_string(self):
        self.assertEqual(self.agent.Laptop(NTFY).server_hosts, ["ntfy.sh"])

    def test_outbox_goes_to_first_server_that_takes_it(self):
        agent = self.agent
        folder = os.path.join(agent.STATE_DIR, "sittings", "made-up", "outbox")
        os.makedirs(folder)
        with open(os.path.join(folder, "tdsb-111.json"), "w") as handle:
            json.dump({"sitting": "made-up", "kind": "hand-in", "user": "tdsb-111"}, handle)
        tried = []

        def fake(request, timeout):
            tried.append(request.full_url)
            if request.full_url.startswith(LAB):
                raise OSError("down")
            return Stream(b"{}")
        with mock.patch.object(agent.urllib.request, "urlopen", fake), \
                mock.patch.object(agent, "body_for", lambda message: "sealed"):
            agent.send_outbox([LAB, NTFY], "answers")
            agent.send_outbox([LAB, NTFY], "answers")          # sent: not again
        self.assertEqual(tried, [f"{LAB}/answers", f"{NTFY}/answers"])
        self.assertTrue(os.path.exists(os.path.join(agent.STATE_DIR, "sittings", "made-up", "sent", "tdsb-111.json")))

    def test_outbox_kept_when_every_server_is_down(self):
        agent = self.agent
        folder = os.path.join(agent.STATE_DIR, "sittings", "made-up", "outbox")
        os.makedirs(folder)
        with open(os.path.join(folder, "tdsb-111.json"), "w") as handle:
            json.dump({"sitting": "made-up", "kind": "hand-in", "user": "tdsb-111"}, handle)

        def down(request, timeout):
            raise OSError("down")
        with mock.patch.object(agent.urllib.request, "urlopen", down), \
                mock.patch.object(agent, "body_for", lambda message: "sealed"):
            agent.send_outbox([LAB, NTFY], "answers")
        self.assertFalse(os.path.exists(os.path.join(agent.STATE_DIR, "sittings", "made-up", "sent")))


# ---------------------------------------------------------------- inventory report

class ReporterSend(unittest.TestCase):
    def test_first_server_that_takes_it(self):
        reporter = t22.rep
        tried = []

        def fake(request, timeout):
            tried.append(request.full_url)
            if request.full_url.startswith(LAB):
                raise OSError("down")
            return Stream(b"{}")
        with mock.patch.object(reporter.urllib.request, "urlopen", fake):
            self.assertEqual(reporter.send([LAB, NTFY], "inv", "body"), NTFY)
        self.assertEqual(tried, [f"{LAB}/inv", f"{NTFY}/inv"])

    def test_all_down_is_an_oserror(self):
        reporter = t22.rep

        def down(request, timeout):
            raise OSError("down")
        with mock.patch.object(reporter.urllib.request, "urlopen", down):
            with self.assertRaises(OSError):
                reporter.send([LAB, NTFY], "inv", "body")


class ReporterMessageKey(unittest.TestCase):
    """0029's report had lost 0023's message key; 0038 has it again."""

    def test_message_key_made_once_and_reported(self):
        reporter = t22.rep
        state = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, state)
        real_read = reporter.read
        with mock.patch.object(reporter, "STATE_DIR", state), \
                mock.patch.object(reporter, "read",
                                  lambda path: "machine-1" if path == "/etc/machine-id" else real_read(path)):
            first = reporter.message_key()
            self.assertEqual(reporter.message_key(), first)
        self.assertEqual(len(__import__("base64").b64decode(first)), 32)
        self.assertEqual(os.stat(os.path.join(state, "message-key")).st_mode & 0o777, 0o600)
        with open(REPORTER) as handle:
            self.assertIn('"message_pubkey": message_key(),', handle.read())


# ---------------------------------------------------------------- install.sh

class InstallScript(unittest.TestCase):
    def test_script(self):
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read()
        self.assertTrue(script.startswith("#!/bin/bash\n"))
        self.assertIn('source "$LAB_UPDATER_HELPERS"', script)
        for path in list(CONFIGS) + ["usr/local/lib/lab-messages/lab-messages-listener.py",
                                     "usr/local/lib/lab-quiz/lab-quiz-agent.py",
                                     "usr/local/lib/lab-inventory/lab-inventory-report"]:
            self.assertIn(f"files/{path}", script)
            self.assertTrue(os.path.exists(os.path.join(FILES, path)), path)
        self.assertIn("systemctl restart lab-messages.service", script)
        self.assertIn("systemctl restart lab-quiz.service", script)
        self.assertNotIn("request_reboot", script)
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(UPDATE, "install.sh")]).returncode, 0)

    def test_programs_compile(self):
        for path in (LISTENER, AGENT, REPORTER):
            with open(path) as handle:
                compile(handle.read(), path, "exec")


if __name__ == "__main__":
    unittest.main()
