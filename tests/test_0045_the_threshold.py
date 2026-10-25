#!/usr/bin/env python3
"""Tests for 0045-the-threshold: the laptop agent that signs students in to
the class RPG. With the project's real game server (rpg/server, when this
checkout sits in the project) it plays the whole sign-in: a world is open,
the agent asks with this laptop's (throwaway) key, gets a one-time link
and the link signs the browser in. Throwaway keys, folders and ports; never
the real server.

    python3 -I update-repo/tests/test_0045_the_threshold.py
"""

import asyncio
import http.client
import importlib.machinery
import importlib.util
import json
import os
import pwd
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0045-the-threshold")
FILES = os.path.join(UPDATE, "files")
AGENT = os.path.join(FILES, "usr", "local", "lib", "lab-rpg", "lab-rpg-agent.py")
PROJECT = os.path.join(HERE, "..", "..")
SERVER = os.path.join(PROJECT, "rpg", "server", "threshold_server.py")
HAVE_SERVER = os.path.exists(SERVER)
ME = pwd.getpwuid(os.getuid()).pw_name

WORK = tempfile.mkdtemp(prefix="lab-rpg-test-")
KEY = os.path.join(WORK, "laptop-key")
subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", KEY], check=True)


def free_port():
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


PORT = free_port()
os.environ.update({"LAB_RPG_CONFIG": os.path.join(WORK, "config"), "LAB_RPG_RUN_DIR": os.path.join(WORK, "run"),
                   "LAB_RPG_LAPTOP_KEY": KEY, "LAB_RPG_HOSTNAME": "lab-test1", "LAB_RPG_ALLOW_HTTP": "1"})


def load(name, path):
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


agent = load("lab_rpg_agent", AGENT)


def write_config(url):
    with open(os.environ["LAB_RPG_CONFIG"], "w") as handle:
        handle.write(f"# test\nRPG_URL={url}\n")


class Config(unittest.TestCase):
    def test_shipped_config_is_https(self):
        with open(os.path.join(FILES, "etc", "lab-rpg", "config")) as handle:
            self.assertIn("RPG_URL=https://lab-messages.tail72844f.ts.net/rpg", handle.read())

    def test_url_rules(self):
        write_config("https://example.test/rpg/")
        self.assertEqual(agent.rpg_url(), "https://example.test/rpg")
        write_config("ftp://example.test/rpg")
        self.assertIsNone(agent.rpg_url())
        agent.ALLOW_HTTP = False
        write_config("http://127.0.0.1:1/rpg")
        self.assertIsNone(agent.rpg_url())
        agent.ALLOW_HTTP = True


class MenuRequests(unittest.TestCase):
    def setUp(self):
        agent.prepare_dirs()

    def test_owner_is_who_asked_and_files_go(self):
        open(os.path.join(agent.requests_dir(), "ask.1"), "w").close()
        os.symlink("/etc/passwd", os.path.join(agent.requests_dir(), "ask.link"))
        self.assertEqual(agent.menu_requests(), {ME})
        self.assertEqual(os.listdir(agent.requests_dir()), [])
        self.assertEqual(os.stat(agent.requests_dir()).st_mode & 0o7777, 0o1733)

    def test_launcher_drops_a_request(self):
        launcher = os.path.join(FILES, "usr", "local", "bin", "the-threshold")
        with open(launcher) as handle:
            script = handle.read().replace("/run/lab-rpg/requests", agent.requests_dir())
        subprocess.run(["sh", "-c", script], check=True)
        self.assertEqual(agent.menu_requests(), {ME})


class Students(unittest.TestCase):
    def test_admins_and_sessions_without_a_desktop_are_skipped(self):
        saved = agent.logged_in_users, agent.is_admin, agent.has_desktop
        agent.logged_in_users = lambda: ["administrator", "tdsb-100000001", "tdsb-100000002"]
        agent.is_admin = lambda u: u == "administrator"
        agent.has_desktop = lambda u: u != "tdsb-100000002"
        try:
            self.assertEqual(agent.students(), ["tdsb-100000001"])
        finally:
            agent.logged_in_users, agent.is_admin, agent.has_desktop = saved


@unittest.skipUnless(HAVE_SERVER, "needs the project's game server (rpg/server)")
class WholeSignIn(unittest.TestCase):
    """The agent against the real Threshold server on a spare port."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.dirname(SERVER))
        cls.ts = load("threshold_server", SERVER)
        inventory = os.path.join(WORK, "inventory.json")
        with open(KEY + ".pub") as handle:
            public = handle.read().strip()
        with open(inventory, "w") as handle:
            json.dump({"laptop": {"pubkey": public, "report": {"name": "lab-test1"}}}, handle)
        cls.world = cls.ts.World("test", ["tdsb-100000001", ME], folder=os.path.join(WORK, "world"))
        cls.loop = asyncio.new_event_loop()
        ready = threading.Event()

        async def serve():
            started = asyncio.Event()
            task = asyncio.create_task(cls.ts.run(cls.world, "127.0.0.1", PORT, ready=started, inventory=inventory))
            await started.wait()
            ready.set()
            await task

        cls.thread = threading.Thread(target=lambda: cls.loop.run_until_complete(serve()), daemon=True)
        cls.thread.start()
        ready.wait(10)

    def setUp(self):
        time.sleep(2.1)                                  # the server's pause between one laptop's requests
        write_config(f"http://127.0.0.1:{PORT}/rpg")
        agent.prepare_dirs()
        agent.menu_requests()
        self.opened = []
        self.saved = agent.students, agent.open_game
        agent.open_game = lambda user, link: self.opened.append((user, link)) or True
        agent.students = lambda: self.users
        self.users = ["tdsb-100000001"]
        self.agent = agent.Agent()

    def tearDown(self):
        agent.students, agent.open_game = self.saved

    def test_opens_once_per_session_and_the_link_signs_in(self):
        self.agent.tick(now=1000)
        self.assertEqual(len(self.opened), 1)
        user, link = self.opened[0]
        self.assertEqual(user, "tdsb-100000001")
        self.assertTrue(link.startswith(f"http://127.0.0.1:{PORT}/rpg/?t="))
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", link.split(str(PORT), 1)[1])
        response = conn.getresponse()
        self.assertEqual(response.status, 303)
        self.assertIn("HttpOnly", response.getheader("Set-Cookie"))
        self.agent.tick(now=1030)
        self.assertEqual(len(self.opened), 1, "once per session")

    def test_menu_opens_it_again(self):
        self.users = [ME]                                # the request file's owner is whoever runs the test
        self.agent.tick(now=2000)
        time.sleep(2.1)
        open(os.path.join(agent.requests_dir(), "ask.1"), "w").close()
        self.agent.tick(now=2005)
        self.assertEqual([user for user, _ in self.opened], [ME, ME])

    def test_other_classes_are_left_alone(self):
        self.users = ["tdsb-999999999"]
        self.agent.tick(now=3000)
        self.assertEqual(self.opened, [])

    def test_no_world_no_requests(self):
        write_config(f"http://127.0.0.1:{PORT + 1}/rpg")        # nothing listens there
        self.agent.tick(now=4000)
        self.assertEqual(self.opened, [])


class Install(unittest.TestCase):
    def test_installs_everything_it_ships(self):
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read()
        for root, _, names in os.walk(FILES):
            for name in names:
                shipped = os.path.relpath(os.path.join(root, name), UPDATE)
                self.assertIn(shipped, script)
        self.assertIn("systemctl enable lab-rpg.service", script)


if __name__ == "__main__":
    unittest.main()
