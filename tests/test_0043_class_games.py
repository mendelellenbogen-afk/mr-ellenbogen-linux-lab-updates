#!/usr/bin/env python3
"""Tests for 0043-class-games: the laptop agent (signed events, game state,
cards for one student only, posts and guesses signed + encrypted), the
teacher's tools/lab-game host, and a whole game end to end through a
private local ntfy server, with the real game window on a private Broadway
display. Throwaway keys, folders and topics; never the real servers.

    python3 -I update-repo/tests/test_0043_class_games.py
"""

import base64
import importlib.machinery
import importlib.util
import json
import os
import pwd
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, x25519

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0043-class-games")
FILES = os.path.join(UPDATE, "files")
AGENT = os.path.join(FILES, "usr", "local", "lib", "lab-game", "lab-game-agent.py")
WINDOW = os.path.join(FILES, "usr", "local", "lib", "lab-game", "game-window.py")
CONFIG = os.path.join(FILES, "etc", "lab-game", "config")
PROJECT = os.path.join(HERE, "..", "..")
LAB_GAME = os.path.join(PROJECT, "tools", "lab-game")
HAVE_TOOLS = os.path.exists(LAB_GAME)
ME = pwd.getpwuid(os.getuid()).pw_name

WORK = tempfile.mkdtemp(prefix="lab-game-test-")


def load(name, path):
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def read(path):
    with open(path) as handle:
        return handle.read()


def read_json(path):
    return json.loads(read(path))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def keygen(path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", path], check=True)
    with open(path + ".pub") as handle:
        return handle.read().strip()


# ----- throwaway keys and files, shared by every test -----

LAB_KEY = os.path.join(WORK, "lab-key")
lab_public = keygen(LAB_KEY)
SIGNERS = os.path.join(WORK, "allowed_signers")
with open(SIGNERS, "w") as handle:
    handle.write(f"teacher@test {lab_public}\n")
OTHER_KEY = os.path.join(WORK, "other-key")
keygen(OTHER_KEY)

LAPTOP_KEY = os.path.join(WORK, "laptop-key")
laptop_public = keygen(LAPTOP_KEY)
MESSAGE_KEY = os.path.join(WORK, "message-key")
_message = x25519.X25519PrivateKey.generate()
with open(MESSAGE_KEY, "wb") as handle:
    handle.write(_message.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                        serialization.NoEncryption()))
MESSAGE_PUB = base64.b64encode(_message.public_key().public_bytes(serialization.Encoding.Raw,
                                                                  serialization.PublicFormat.Raw)).decode()
TEACHER_PEM = os.path.join(WORK, "teacher-key.pem")
TEACHER_PUB = os.path.join(WORK, "teacher-key.pub.pem")
_teacher = rsa.generate_private_key(public_exponent=65537, key_size=2048)
with open(TEACHER_PEM, "wb") as handle:
    handle.write(_teacher.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
with open(TEACHER_PUB, "wb") as handle:
    handle.write(_teacher.public_key().public_bytes(serialization.Encoding.PEM,
                                                    serialization.PublicFormat.SubjectPublicKeyInfo))
INVENTORY = os.path.join(WORK, "inventory.json")
with open(INVENTORY, "w") as handle:
    json.dump({"SER1": {"pubkey": laptop_public, "report": {"name": "lab-a", "message_pubkey": MESSAGE_PUB}},
               "SER2": {"pubkey": "ssh-ed25519 AAAAother", "report": {"name": "lab-b"}}}, handle)

PORT = free_port()
SERVER = f"http://127.0.0.1:{PORT}"
TOPIC = "test-game-" + os.urandom(4).hex()
ACTION_TOPIC = "test-game-actions-" + os.urandom(4).hex()
TEST_CONFIG = os.path.join(WORK, "config")
with open(TEST_CONFIG, "w") as handle:
    handle.write(f"SERVER={SERVER}\nGAME_TOPIC={TOPIC}\nGAME_ACTION_TOPIC={ACTION_TOPIC}\n")
RUN_DIR = os.path.join(WORK, "run")

os.environ.update({
    "LAB_GAME_CONFIG": TEST_CONFIG, "LAB_GAME_SIGNERS": SIGNERS, "LAB_GAME_RUN_DIR": RUN_DIR,
    "LAB_GAME_HOSTNAME": "lab-a", "LAB_GAME_MESSAGE_KEY": MESSAGE_KEY, "LAB_GAME_LAPTOP_KEY": LAPTOP_KEY,
    "LAB_GAME_TEACHER_KEY": TEACHER_PUB, "LAB_GAME_ALLOW_HTTP": "1",
    "LAB_GAME_SERVER": SERVER, "LAB_GAME_TOPIC": TOPIC, "LAB_GAME_ACTION_TOPIC": ACTION_TOPIC,
    "LAB_GAME_DATA": os.path.join(WORK, "lab-games"), "LAB_INVENTORY_FILE": INVENTORY,
    "LAB_INVENTORY_KEY": TEACHER_PEM, "LAB_GAME_SIGNING_KEY": LAB_KEY,
})

agent = load("lab_game_agent43", AGENT)
lab_game = load("lab_game_tool43", LAB_GAME) if HAVE_TOOLS else None


def signed(payload, key=LAB_KEY, namespace="lab-game"):
    text = json.dumps(payload)
    path = os.path.join(tempfile.mkdtemp(dir=WORK), "to-sign")
    with open(path, "w") as handle:
        handle.write(text)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", key, "-n", namespace, path], check=True)
    with open(path + ".sig") as handle:
        return json.dumps({"payload": text, "sig": handle.read()})


def start_event(game="g1", seq=1, started=None, accounts=None):
    started = int(started or time.time())
    return {"v": 1, "game": game, "seq": seq, "sent": started, "type": "start", "title": "Room", "intro": "Story",
            "minutes": 30, "started": started, "deadline": started + 1800, "accounts": accounts,
            "cost": {"free_minutes": 10, "start": 15, "step": 5, "every_minutes": 5, "max": 60},
            "locks": [{"id": "vault", "name": "Vault", "prompt": "4 digits", "kind": "number", "requires": []},
                      {"id": "exit", "name": "Exit", "prompt": "word", "kind": "word", "requires": ["vault"],
                       "final": True}]}


class Config(unittest.TestCase):
    def test_real_config(self):
        saved = agent.CONFIG_FILE
        agent.CONFIG_FILE = CONFIG
        try:
            servers, topic, actions = agent.read_config()
        finally:
            agent.CONFIG_FILE = saved
        self.assertEqual(servers, ["https://lab-messages.tail72844f.ts.net", "https://ntfy.sh"])
        self.assertTrue(topic.startswith("mrellenbogen-lab-game-") and actions.startswith("mrellenbogen-lab-game-actions-"))
        self.assertNotEqual(topic, actions)
        if HAVE_TOOLS:
            source = read(LAB_GAME)
            self.assertIn(topic, source)
            self.assertIn(actions, source)

    def test_http_only_when_testing(self):
        saved = agent.ALLOW_HTTP
        agent.ALLOW_HTTP = False
        try:
            with self.assertRaises(RuntimeError):
                agent.read_config()
        finally:
            agent.ALLOW_HTTP = saved


class Signatures(unittest.TestCase):
    def test_only_lab_signed_game_messages(self):
        payload = start_event()
        self.assertEqual(agent.open_signed(signed(payload))["game"], "g1")
        self.assertIsNone(agent.open_signed(signed(payload, key=OTHER_KEY)))
        self.assertIsNone(agent.open_signed(signed(payload, namespace="lab-message")))     # a pop-up's signature
        self.assertIsNone(agent.open_signed("not json"))
        self.assertIsNone(agent.open_signed(signed({"game": "g1"})))                     # no seq/type


class GameState(unittest.TestCase):
    def setUp(self):
        self.state = agent.State()
        self.now = time.time()
        self.state.apply(start_event(started=self.now), self.now)

    def event(self, seq, kind, **fields):
        return dict({"v": 1, "game": "g1", "seq": seq, "sent": int(self.now), "type": kind}, **fields)

    def test_start(self):
        d = self.state.data
        self.assertEqual((d["title"], len(d["locks"]), d["result"]), ("Room", 2, None))
        self.assertTrue(self.state.live(self.now))
        self.assertFalse(self.state.live(self.now + 1806))

    def test_events_count_once_and_build_the_state(self):
        apply = lambda e: self.state.apply(e, self.now)
        post = self.event(2, "post", post={"n": 1, "who": "Lime Otter", "color": "#5aa02c", "text": "hi", "at": 1})
        self.assertTrue(apply(post))
        self.assertFalse(apply(post))                                    # from the other server
        apply(self.event(4, "hide", n=2))                               # hidden before it arrived
        apply(self.event(3, "post", post={"n": 2, "who": "X", "text": "rude", "at": 2}))
        self.assertEqual([(p["n"], p["hidden"]) for p in self.state.data["posts"]], [(1, False), (2, True)])
        apply(self.event(6, "guess", lock="vault", who="Lime Otter", text="1234", cost=15,
                         deadline=int(self.now) + 1785))
        apply(self.event(5, "time", deadline=int(self.now) + 1900, change=100))      # older: deadline kept
        self.assertEqual(self.state.data["deadline"], int(self.now) + 1785)
        apply(self.event(7, "open", lock="vault", who="Lime Otter", color="#5aa02c", reveal="Inside: B"))
        vault = self.state.lock_named("vault")
        self.assertEqual((vault["open"], vault["by"], vault["reveal"]), (True, "Lime Otter", "Inside: B"))
        apply(self.event(8, "hint", text="Look at the map"))
        apply(self.event(9, "end", result="escaped", left=600))
        self.assertEqual(self.state.data["result"], "escaped")
        feed = [f["text"] for f in self.state.data["feed"]]
        self.assertIn("Lime Otter tried “1234” on Vault: wrong  (−15 s)", feed)
        self.assertIn("Lime Otter opened Vault!", feed)
        self.assertIn("Hint from your teacher: Look at the map", feed)
        self.assertFalse(self.state.live(self.now))

    def test_other_and_old_games(self):
        self.assertFalse(self.state.apply(dict(self.event(2, "hint", text="x"), game="other"), self.now))
        self.assertFalse(self.state.apply(start_event("old", started=self.now - 600), self.now))   # older game
        self.assertEqual(self.state.game, "g1")
        self.assertTrue(self.state.apply(start_event("g2", started=self.now + 60), self.now + 60))
        self.assertEqual((self.state.game, self.state.data["posts"]), ("g2", []))
        fresh = agent.State()
        self.assertFalse(fresh.apply(start_event("ancient", started=self.now - 4 * 3600), self.now))

    def test_state_file_is_public_and_has_no_cards(self):
        saved = agent.RUN_DIR
        agent.RUN_DIR = tempfile.mkdtemp(dir=WORK)
        try:
            self.state.write()
            path = os.path.join(agent.RUN_DIR, "state.json")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        finally:
            agent.RUN_DIR = saved


class DealsAndActions(unittest.TestCase):
    def setUp(self):
        self.saved = agent.RUN_DIR
        agent.RUN_DIR = tempfile.mkdtemp(dir=WORK)
        agent.prepare_dirs()
        self.state = agent.State()
        self.state.apply(start_event(), time.time())

    def tearDown(self):
        agent.RUN_DIR = self.saved

    def test_cards_are_for_one_student_only(self):
        payload = {"game": "g1", "seq": 5, "type": "deal", "account": ME, "laptops": ["lab-a"],
                   "codename": "Teal Lynx", "color": "#11878f", "cards": [{"title": "Map", "text": "X marks"}]}
        self.assertTrue(agent.write_deal(payload))
        path = os.path.join(agent.RUN_DIR, f"deal-{os.getuid()}.json")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(read_json(path)["cards"], [{"title": "Map", "text": "X marks"}])
        self.assertFalse(agent.write_deal(dict(payload, seq=3, cards=[])))          # an older deal
        self.assertFalse(agent.write_deal(dict(payload, account="no-such-user-43")))

    @unittest.skipUnless(HAVE_TOOLS, "tools/lab-game is only on the teacher's computer")
    def test_encrypted_deal_through_handle_body(self):
        host = lab_game.Host(lab_game.gamelib.Game.new("g1", lab_game.gamelib.load_room("ghost-in-the-machine")))
        event = {"type": "deal", "seq": 9, "account": ME, "laptops": ["lab-a"], "codename": "Teal Lynx",
                 "color": "#11878f", "cards": [{"title": "T", "text": "secret clue"}]}
        body = host.body(event).decode()
        self.assertNotIn("secret clue", body)
        self.assertNotIn(ME, body)
        agent.handle_body(self.state, body)
        deal = read_json(os.path.join(agent.RUN_DIR, f"deal-{os.getuid()}.json"))
        self.assertEqual(deal["codename"], "Teal Lynx")
        saved = agent.HOSTNAME
        agent.HOSTNAME = "lab-z"                     # another laptop can't open it
        try:
            os.unlink(os.path.join(agent.RUN_DIR, f"deal-{os.getuid()}.json"))
            agent.handle_body(self.state, body)
            self.assertFalse(os.path.exists(os.path.join(agent.RUN_DIR, f"deal-{os.getuid()}.json")))
        finally:
            agent.HOSTNAME = saved

    def drop(self, action):
        path = os.path.join(agent.action_dir(), f"{os.urandom(4).hex()}.json")
        with open(path, "w") as handle:
            handle.write(action if isinstance(action, str) else json.dumps(action))

    def test_drop_folder_is_sticky(self):
        self.assertEqual(os.stat(agent.action_dir()).st_mode & 0o7777, 0o1733)

    def test_actions_take_the_account_from_the_file_owner(self):
        self.drop({"game": "g1", "type": "post", "text": "digit 1 is 7", "user": "someone-else"})
        self.drop({"game": "g1", "type": "guess", "lock": "vault", "text": "7343"})
        self.drop({"game": "g1", "type": "guess", "lock": "nope", "text": "1"})
        self.drop({"game": "old", "type": "post", "text": "x"})
        self.drop({"game": "g1", "type": "join"})                     # only the agent joins
        self.drop("not json")
        self.drop("x" * 5000)
        os.symlink("/etc/hostname", os.path.join(agent.action_dir(), "link.json"))
        outbox = []
        agent.collect_actions(self.state, outbox)
        self.assertEqual([(a["type"], a["user"], a["laptop"]) for a in outbox],
                         [("post", ME, "lab-a"), ("guess", ME, "lab-a")])
        self.assertEqual(os.listdir(agent.action_dir()), [])

    @unittest.skipUnless(HAVE_TOOLS, "tools/lab-game is only on the teacher's computer")
    def test_teacher_accepts_genuine_actions_only(self):
        keys = lab_game.known_keys()
        action = agent.make_action(self.state, ME, "post", text="hello")
        body = agent.action_body(action).decode()
        self.assertNotIn("hello", body)
        self.assertEqual(lab_game.check_action(body, _teacher, keys)["text"], "hello")
        forged = agent.action_body(dict(action, laptop="lab-b")).decode()            # wrong laptop key
        self.assertIsNone(lab_game.check_action(forged, _teacher, keys))
        self.assertIsNone(lab_game.check_action("garbage", _teacher, keys))


class Sessions(unittest.TestCase):
    def setUp(self):
        self.saved = {name: getattr(agent, name) for name in ("logged_in_users", "run_as", "is_admin", "RUN_DIR")}
        agent.RUN_DIR = tempfile.mkdtemp(dir=WORK)
        self.opened = []
        agent.logged_in_users = lambda: [ME]
        agent.run_as = lambda user, command: self.opened.append((user, command)) or True
        self.admin = False
        agent.is_admin = lambda user: self.admin
        self.state = agent.State()

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(agent, name, value)

    @unittest.skipUnless(os.path.exists(f"/run/user/{os.getuid()}/bus"), "needs a desktop session bus")
    def test_window_once_and_join_until_cards_arrive(self):
        now = time.time()
        self.state.apply(start_event(started=now), now)
        sessions, outbox = agent.Sessions(self.state), []
        sessions.tick(outbox, now)
        sessions.tick(outbox, now + 1)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual([a["type"] for a in outbox], ["join"])
        sessions.tick(outbox, now + agent.JOIN_RETRY_SECONDS + 1)
        self.assertEqual(len(outbox), 2)                                             # tried again
        with open(os.path.join(agent.RUN_DIR, f"deal-{os.getuid()}.json"), "w") as handle:
            json.dump({"game": "g1"}, handle)
        sessions.tick(outbox, now + 3 * agent.JOIN_RETRY_SECONDS)
        self.assertEqual(len(outbox), 2)                                             # has cards now

    @unittest.skipUnless(os.path.exists(f"/run/user/{os.getuid()}/bus"), "needs a desktop session bus")
    def test_class_only_and_admins_get_the_big_screen(self):
        now = time.time()
        self.state.apply(start_event(started=now, accounts=[agent.account_tag("g1", "someone-else")]), now)
        outbox = []
        agent.Sessions(self.state).tick(outbox, now)
        self.assertEqual((self.opened, outbox), ([], []))                           # not in the class
        self.admin = True
        agent.Sessions(self.state).tick(outbox, now)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(outbox, [])                                                 # admins don't play
        self.state.apply(dict(start_event(started=now), seq=9, type="end", result="ended"), now)

    def test_nothing_without_a_live_game(self):
        outbox = []
        agent.Sessions(self.state).tick(outbox)
        self.assertEqual((self.opened, outbox), ([], []))


@unittest.skipUnless(HAVE_TOOLS and shutil.which("ntfy") and shutil.which("gtk4-broadwayd"),
                     "needs tools/lab-game, ntfy and gtk4-broadwayd")
class WholeGame(unittest.TestCase):
    """Teacher host -> local ntfy -> agent -> real window -> agent -> host -> ... -> escape."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(dir=WORK)
        server_yml = os.path.join(cls.dir, "server.yml")
        with open(server_yml, "w") as handle:
            handle.write(f"listen-http: 127.0.0.1:{PORT}\ncache-file: {cls.dir}/cache.db\ncache-duration: 1h\n"
                         "visitor-request-limit-burst: 100000\nvisitor-request-limit-replenish: 1ms\n"
                         "visitor-message-daily-limit: 0\n")
        cls.ntfy = subprocess.Popen(["ntfy", "serve", "-c", server_yml], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        cls.display = f":{40 + os.getpid() % 50}"
        cls.runtime = os.path.join(cls.dir, "runtime")
        os.makedirs(cls.runtime, mode=0o700)
        cls.broadway = subprocess.Popen(["gtk4-broadwayd", cls.display], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, env=dict(os.environ, XDG_RUNTIME_DIR=cls.runtime))
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        for process in (cls.ntfy, cls.broadway):
            process.terminate()
            process.wait()

    def setUp(self):
        self.saved = {name: getattr(agent, name) for name in ("logged_in_users", "run_as", "is_admin", "RUN_DIR")}
        agent.RUN_DIR = RUN_DIR
        agent.prepare_dirs()
        agent.logged_in_users = lambda: [ME]
        agent.run_as = lambda user, command: True
        agent.is_admin = lambda user: False
        self.state = agent.State()
        self.servers, _topic, self.action_topic = agent.read_config()
        threading.Thread(target=self.listen, daemon=True).start()
        self.sessions, self.outbox = agent.Sessions(self.state), []

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(agent, name, value)

    def listen(self):
        while True:
            try:
                agent.listen_once(self.state, SERVER, TOPIC, "all")
            except Exception:
                time.sleep(0.2)

    def laptop_round(self):
        agent.collect_actions(self.state, self.outbox)
        self.sessions.tick(self.outbox)
        agent.send_actions(self.state, self.servers, self.action_topic, self.outbox)

    def until(self, check, host, key, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            self.laptop_round()
            host.step(key)
            if check():
                return True
            time.sleep(0.3)
        return False

    def run_window(self, script, wait_ms, host, key, projector="0"):
        env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=self.display, XDG_RUNTIME_DIR=self.runtime,
                   LAB_GAME_RUN_DIR=RUN_DIR, LAB_GAME_APP_ID=f"com.school.LabGameTest{os.urandom(3).hex()}",
                   LAB_GAME_PROJECTOR=projector, LAB_GAME_SOUND="", LAB_GAME_SELFTEST=script,
                   LAB_GAME_SELFTEST_WAIT=str(wait_ms))
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        window = subprocess.Popen(["python3", "-I", WINDOW], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True)
        end = time.time() + wait_ms / 1000 + 10
        while window.poll() is None and time.time() < end:
            self.laptop_round()
            host.step(key)
            time.sleep(0.3)
        out, err = window.communicate(timeout=30)
        return out, err

    def test_a_whole_game(self):
        room = lab_game.gamelib.load_room("ghost-in-the-machine")
        game = lab_game.gamelib.Game.new("ghost-test-" + os.urandom(3).hex(), room, accounts=[ME])
        host = lab_game.Host(game, rng=random.Random(7))
        host.queue([host.start_event()])
        key = lab_game.private_key()
        self.assertNotIn(ME, json.dumps(host.data["outbox"][0]))                    # only tags go out

        # The laptop learns about the game, opens the window and joins; the cards arrive.
        deal_path = os.path.join(RUN_DIR, f"deal-{os.getuid()}.json")
        self.assertTrue(self.until(lambda: (read_json(deal_path).get("game") == game.data["game"]
                                            if os.path.exists(deal_path) else False), host, key),
                        "the cards never arrived")
        deal = read_json(deal_path)
        self.assertEqual(len(deal["cards"]), 2)
        codename = deal["codename"]
        self.assertEqual(game.data["players"][ME]["codename"], codename)

        # Through the real window: a wrong guess, the right code, a post.
        out, err = self.run_window("guess:vault:1111|post:Digit 2 is 3!", 2500, host, key)
        self.assertIn("TITLE:Ghost in the Machine", out, err)
        self.assertIn(f"ME:{codename}", out)
        self.assertEqual(out.count("CARD:"), 2)
        self.assertTrue(self.until(lambda: len(self.state.data["posts"]) == 1, host, key))
        time.sleep(agent.TICK_SECONDS + 4)          # the window's guess gap and the host's
        out, err = self.run_window("guess:vault:7343", 3500, host, key)
        self.assertTrue(self.until(lambda: self.state.lock_named("vault")["open"], host, key))
        out, err = self.run_window("", 300, host, key)
        self.assertIn("LOCK:vault:OPEN · " + codename + ":no-input", out, err)
        self.assertIn("LOCK:firewall:LOCKED:input", out)
        self.assertIn("LOCK:exit:SEALED:no-input", out)
        self.assertIn(f"POST:{codename}:Digit 2 is 3!", out)
        self.assertIn(f"FEED:{codename} opened The Memory Vault!", out)
        self.assertIn(f"FEED:{codename} tried “1111” on The Memory Vault: wrong", out)
        self.assertIn("COST:Wrong guesses are free for now", out)

        # The teacher hides the post and sends a hint; the big screen shows it all, without cards.
        lab_game.control(game.data["game"], {"cmd": "hide", "n": 1})
        lab_game.control(game.data["game"], {"cmd": "hint", "lock": "echo"})
        self.assertTrue(self.until(lambda: self.state.data["hints"] and self.state.data["posts"][0]["hidden"],
                                   host, key))
        out, err = self.run_window("", 300, host, key, projector="1")
        self.assertNotIn("POST:", out, err)
        self.assertNotIn("CARD:", out)
        self.assertIn("FEED:Hint from your teacher: The Echo Chamber: Someone holds", out)

        # The rest of the locks (straight through the host), then the escape.
        for lock, answer in (("echo", "moonlight"), ("firewall", "radar"), ("exit", "reboot")):
            game.data["players"][ME]["last_guess"] = 0
            host.queue(game.guess(ME, lock, answer, time.time()))
        self.assertTrue(self.until(lambda: self.state.data["result"] == "escaped", host, key))
        out, err = self.run_window("", 300, host, key)
        self.assertIn("BANNER:YOU ESCAPED!", out, err)
        self.assertNotIn(":input", out)
        record = read_json(os.path.join(os.environ["LAB_GAME_DATA"], game.data["game"], "game.json"))
        self.assertEqual(record["result"], "escaped")
        self.assertEqual(os.stat(os.path.join(os.environ["LAB_GAME_DATA"], game.data["game"], "game.json")).st_mode
                         & 0o777, 0o600)


class Install(unittest.TestCase):
    def test_install_script_installs_everything_it_ships(self):
        script = read(os.path.join(UPDATE, "install.sh"))
        for root, dirs, files in os.walk(FILES):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.relpath(os.path.join(root, name), FILES)
                self.assertIn(f"files/{path} ", script, path)
        self.assertIn("systemctl enable lab-game.service", script)


def tearDownModule():
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
