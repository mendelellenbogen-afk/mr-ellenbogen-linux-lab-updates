#!/usr/bin/env python3
"""Class games (update 0043, crews from 0044): the laptop's side of the teacher's escape rooms.

Runs as root (lab-game.service). It listens on the game topic for events
from the teacher's tools/lab-game, keeps the game's public state in
/run/lab-game/state.json for the game window, and opens that window in
every desktop session while a game is on.

Rules:
  * Only events signed with the lab key (namespace "lab-game", key pinned
    in /etc/lab-updater/allowed_signers) count. Each carries the game id
    and a sequence number; repeats (both servers, reconnects) count once.
  * On start (and after a restart) the agent reads the last 3 hours of the
    topic, so a laptop that logs in late catches up on the whole game.
  * Who plays: "accounts" in the start event is null (everyone) or a list
    of tags, sha256("<game>:<account>")[:16], so the topic never carries
    student IDs. Admin (sudo group) sessions always get the window: theirs
    is the big-screen view for the projector, with no cards.
  * Clue cards ("deal") come encrypted to this laptop's own message key
    (the 0023 envelope) and name the account; they are written to
    /run/lab-game/deal-<uid>.json, readable only by that student.
  * The window drops what the student does (post, guess) as a small file
    in /run/lab-game/actions (sticky, like /tmp). The account comes from
    the file's owner, never from its contents. The agent signs it with
    this laptop's inventory key, encrypts it to the teacher's key and posts
    it on the action topic. Joining is sent by the agent itself when it
    opens a student's window, and again if no cards arrive.
  * Answers are never on the laptop: a guess is checked on the teacher's
    computer, which then publishes whether the lock opened.
  * Servers as in 0038: the lab's own server first, ntfy.sh as fallback.
  * Crews (0044, Cipher Heist): the start event lists the crews; each crew
    has its own locks ("open"/"guess" carry the crew) and its own Clue Wall:
    a crew's posts come encrypted to that crew's laptops only, like cards.
    The deal says which crew the student is in. A wrong guess freezes that
    crew ("frozen_until"); the first crew to open its final lock wins
    (end: result "won", crew).

Event payloads: {"v": 1, "game", "seq", "sent", "type", ...}
  start  {title, intro, minutes, started, deadline, locks: [{id, name, prompt, kind, requires, final}],
          cost, accounts, crews: [{id, name, color}] or absent}
  post   {post: {n, who, color, text, at}}        hide {n}
  guess  {lock, who, color, text, cost, deadline}  open {lock, who, color, reveal}
  hint   {text}   time {deadline, change}   feed {text, color}   end {result, left, opened}
  deal   {account, laptops, codename, color, cards: [{title, text, away}], crew, crew_name, crew_color}
                                                    (encrypted)
  Crew games add "crew" to post (then encrypted to the crew's laptops), guess (+ frozen_until),
  open, hint, feed and end (result "won", crew, crew_name).
"""

import base64
import grp
import hashlib
import json
import os
import pwd
import secrets
import socket
import stat
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONFIG_FILE = os.environ.get("LAB_GAME_CONFIG", "/etc/lab-game/config")
ALLOWED_SIGNERS = os.environ.get("LAB_GAME_SIGNERS", "/etc/lab-updater/allowed_signers")
RUN_DIR = os.environ.get("LAB_GAME_RUN_DIR", "/run/lab-game")
WINDOW = os.environ.get("LAB_GAME_WINDOW", "/usr/local/lib/lab-game/game-window.py")
HOSTNAME = (os.environ.get("LAB_GAME_HOSTNAME") or socket.gethostname()).lower()
MESSAGE_KEY = os.environ.get("LAB_GAME_MESSAGE_KEY", "/var/lib/lab-inventory/message-key")
LAPTOP_KEY = os.environ.get("LAB_GAME_LAPTOP_KEY", "/var/lib/lab-inventory/laptop-key")
TEACHER_KEY = os.environ.get("LAB_GAME_TEACHER_KEY", "/etc/lab-inventory/teacher-key.pub.pem")
ALLOW_HTTP = os.environ.get("LAB_GAME_ALLOW_HTTP") == "1"      # tests with a local server only

NAMESPACE = "lab-game"
CATCH_UP = "3h"                  # read this much of the topic when (re)starting
MAX_GAME_SECONDS = 3 * 3600
READ_TIMEOUT_SECONDS = 90
PRIMARY_RETRY_SECONDS = 300
TICK_SECONDS = 2
JOIN_RETRY_SECONDS = 25
JOIN_TRIES = 6
MAX_POSTS = 300
MAX_FEED = 80
MAX_ACTION_BYTES = 2048
LOCK_KINDS = ("number", "word")
MAX_CREWS = 6


def log(message):
    print(message, flush=True)


def read_config():
    config = {}
    with open(CONFIG_FILE, encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                config[key.strip()] = value.strip()
    servers = []
    for value in (config.get("PRIMARY_SERVER", ""), config.get("SERVER", "")):
        value = value.strip().rstrip("/")
        if (value.startswith("https://") or (ALLOW_HTTP and value.startswith("http://"))) and value not in servers:
            servers.append(value)
    if not servers or not config.get("GAME_TOPIC") or not config.get("GAME_ACTION_TOPIC"):
        raise RuntimeError("the game config needs a server and both topics")
    return servers, config["GAME_TOPIC"], config["GAME_ACTION_TOPIC"]


# ---------- checking what arrives ----------

def principal():
    with open(ALLOWED_SIGNERS, encoding="utf-8") as signers:
        for line in signers:
            if line.strip() and not line.startswith("#"):
                return line.split()[0]
    raise RuntimeError("no trusted key")


def verify(text, signature):
    with tempfile.NamedTemporaryFile("w", suffix=".sig") as sig_file:
        sig_file.write(signature)
        sig_file.flush()
        result = subprocess.run(["/usr/bin/ssh-keygen", "-Y", "verify", "-f", ALLOWED_SIGNERS, "-I", principal(),
                                 "-n", NAMESPACE, "-s", sig_file.name], input=text.encode("utf-8"),
                                capture_output=True)
    return result.returncode == 0


def open_signed(body):
    """The payload dict of a lab-signed game message, or None."""
    try:
        envelope = json.loads(body)
        text, signature = envelope["payload"], envelope["sig"]
        if not isinstance(text, str) or not isinstance(signature, str):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    if not verify(text, signature):
        log("Ignored a game message that isn't signed by the lab key.")
        return None
    try:
        payload = json.loads(text)
        if not (isinstance(payload, dict) and isinstance(payload.get("game"), str)
                and isinstance(payload.get("seq"), int) and isinstance(payload.get("type"), str)):
            return None
        return payload
    except ValueError:
        return None


def open_targeted(body):
    """The signed message inside a targeted envelope for this laptop, else None."""
    try:
        outer = json.loads(body)
        mine = outer["to"].get(HOSTNAME)
        if outer.get("lab_target") != 1 or not mine:
            return None
        raw = base64.b64decode
        with open(MESSAGE_KEY, "rb") as handle:
            private = x25519.X25519PrivateKey.from_private_bytes(handle.read())
        ephemeral = raw(outer["epk"])
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        shared = private.exchange(x25519.X25519PublicKey.from_public_bytes(ephemeral))
        kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                   info=b"lab-target-v1" + ephemeral + public).derive(shared)
        wrapped = raw(mine)
        secret = AESGCM(kek).decrypt(wrapped[:12], wrapped[12:], b"lab-target-key")
        return AESGCM(secret).decrypt(raw(outer["nonce"]), raw(outer["data"]), b"lab-target-msg").decode("utf-8")
    except Exception as error:
        log(f"Ignored cards this laptop can't open ({error.__class__.__name__}).")
        return None


def text(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def account_tag(game_id, account):
    return hashlib.sha256(f"{game_id}:{account.lower()}".encode()).hexdigest()[:16]


# ---------- the game state ----------

class State:
    """The public state of the current game, rebuilt from its events."""

    def __init__(self):
        self.lock = threading.Lock()
        self.game = None
        self.data = {}
        self.seen = set()
        self.deadline_seq = 0
        self.hidden = set()

    def reset(self, game_id):
        self.game = game_id
        self.data = {"game": game_id, "title": "", "intro": "", "minutes": 0, "started": 0, "deadline": 0,
                     "locks": [], "cost": None, "accounts": None, "posts": [], "feed": [], "hints": [],
                     "result": None, "left": 0, "ended_at": None, "seq": 0, "updated": time.time(),
                     "crews": None, "crew_locks": {}, "frozen": {}, "winner": None, "winner_name": None}
        self.seen, self.hidden, self.deadline_seq = set(), set(), 0

    def live(self, now=None):
        now = time.time() if now is None else now
        d = self.data
        return bool(self.game) and d.get("started") and d["result"] is None and now < d["deadline"] + 5

    def feed(self, at, line, color=None, kind="info", crew=None):
        self.data["feed"] = (self.data["feed"] + [{"at": at, "text": line[:300], "color": color, "kind": kind,
                                                   "crew": crew}])[-MAX_FEED:]

    def crew_of(self, event):
        """The event's crew if this is a crew game and it names one of its crews."""
        crew = event.get("crew")
        return crew if self.data.get("crews") and crew in self.data["crew_locks"] else None

    def set_deadline(self, value, seq):
        value = number(value)
        if value is not None and seq >= self.deadline_seq:
            self.data["deadline"], self.deadline_seq = value, seq

    def lock_named(self, lock_id):
        return next((lock for lock in self.data["locks"] if lock["id"] == lock_id), None)

    def apply(self, event, now=None):
        """Apply one verified public event. True if anything changed."""
        now = time.time() if now is None else now
        game, seq, kind = event["game"], event["seq"], event["type"]
        if kind == "start":
            started = number(event.get("started"))
            if started is None or now - started > MAX_GAME_SECONDS:
                return False
            if game != self.game:
                if self.game and self.data.get("started", 0) > started:
                    return False                  # an older game's repeat
                self.reset(game)
            locks = []
            for lock in event.get("locks") or []:
                if not isinstance(lock, dict) or lock.get("kind") not in LOCK_KINDS:
                    continue
                old = self.lock_named(lock.get("id")) or {}
                locks.append({"id": text(lock.get("id"), 20), "name": text(lock.get("name"), 80),
                              "prompt": text(lock.get("prompt"), 300), "kind": lock["kind"],
                              "requires": [text(r, 20) for r in lock.get("requires") or [] if isinstance(r, str)],
                              "final": lock.get("final") is True, "open": old.get("open", False),
                              "by": old.get("by"), "color": old.get("color"), "reveal": old.get("reveal")})
            accounts = event.get("accounts")
            crews = []
            for crew in (event.get("crews") or [])[:MAX_CREWS]:
                if isinstance(crew, dict) and isinstance(crew.get("id"), str) and crew["id"]:
                    crews.append({"id": text(crew["id"], 12), "name": text(crew.get("name"), 30),
                                  "color": text(crew.get("color"), 9)})
            if crews:
                old_locks = self.data.get("crew_locks") or {}
                self.data["crews"] = crews
                self.data["crew_locks"] = {c["id"]: old_locks.get(c["id"], {}) for c in crews}
            self.data.update(title=text(event.get("title"), 120), intro=text(event.get("intro"), 1500),
                             minutes=number(event.get("minutes")) or 0, started=started, locks=locks,
                             cost=event.get("cost") if isinstance(event.get("cost"), dict) else None,
                             accounts=[a for a in accounts if isinstance(a, str)] if isinstance(accounts, list) else None)
            self.set_deadline(event.get("deadline"), seq)
            self.seen.add(seq)
            return True
        if game != self.game or seq in self.seen:
            return False
        self.seen.add(seq)
        at = number(event.get("sent")) or int(now)
        d = self.data
        crew = self.crew_of(event)
        if kind == "post":
            post = event.get("post") or {}
            n = number(post.get("n"))
            if n is None or any(p["n"] == n for p in d["posts"]):
                return False
            d["posts"] = sorted(d["posts"] + [{"n": n, "who": text(post.get("who"), 40), "color": text(post.get("color"), 9),
                                               "text": text(post.get("text"), 200), "at": number(post.get("at")) or at,
                                               "hidden": n in self.hidden, "crew": crew}],
                                key=lambda p: p["n"])[-MAX_POSTS:]
        elif kind == "hide":
            n = number(event.get("n"))
            self.hidden.add(n)
            for post in d["posts"]:
                if post["n"] == n:
                    post["hidden"] = True
        elif kind == "guess":
            lock = self.lock_named(event.get("lock"))
            cost = number(event.get("cost")) or 0
            name = lock["name"] if lock else "a lock"
            tail = f"  (−{cost} s)" if cost else ""
            if crew:
                tail = f"  (frozen {cost} s)" if cost else ""
                until = number(event.get("frozen_until"))
                if until is not None:
                    d["frozen"][crew] = max(d["frozen"].get(crew, 0), until)
            self.feed(at, f"{text(event.get('who'), 40)} tried “{text(event.get('text'), 40)}” on {name}: wrong{tail}",
                      text(event.get("color"), 9), "wrong", crew)
            self.set_deadline(event.get("deadline"), seq)
        elif kind == "open":
            lock = self.lock_named(event.get("lock"))
            if lock and crew:
                entry = {"open": True, "by": text(event.get("who"), 40), "color": text(event.get("color"), 9),
                         "reveal": text(event.get("reveal"), 600)}
                d["crew_locks"][crew][lock["id"]] = entry
                self.feed(at, f"{entry['by']} opened {lock['name']}!", entry["color"], "open", crew)
            elif lock and not d.get("crews"):
                lock.update(open=True, by=text(event.get("who"), 40), color=text(event.get("color"), 9),
                            reveal=text(event.get("reveal"), 600))
                self.feed(at, f"{lock['by']} opened {lock['name']}!", lock["color"], "open")
        elif kind == "hint":
            hint = text(event.get("text"), 400)
            d["hints"] = d["hints"] + [{"at": at, "text": hint, "crew": crew}]
            self.feed(at, f"Hint from your teacher: {hint}", None, "hint", crew)
        elif kind == "time":
            change = number(event.get("change")) or 0
            self.set_deadline(event.get("deadline"), seq)
            word = "added" if change >= 0 else "took away"
            self.feed(at, f"Your teacher {word} {abs(change) // 60}:{abs(change) % 60:02d}.", None, "hint")
        elif kind == "feed":
            self.feed(at, text(event.get("text"), 300), text(event.get("color"), 9), crew=crew)
        elif kind == "end":
            result = event.get("result")
            if result in ("escaped", "timeout", "ended") or (result == "won" and crew):
                d.update(result=result, left=number(event.get("left")) or 0, ended_at=at)
                if result == "won":
                    d.update(winner=crew, winner_name=text(event.get("crew_name"), 30))
        else:
            return False
        d["seq"] = max(d["seq"], seq)
        return True

    def write(self):
        os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
        path = os.path.join(RUN_DIR, "state.json")
        with open(path + ".new", "w", encoding="utf-8") as handle:
            json.dump(dict(self.data, updated=time.time()), handle)
        os.chmod(path + ".new", 0o644)
        os.replace(path + ".new", path)


def write_deal(payload):
    """Write a student's cards where only they can read them. True if written."""
    account = payload.get("account")
    if not isinstance(account, str) or not isinstance(payload.get("cards"), list):
        return False
    try:
        entry = pwd.getpwnam(account)
    except KeyError:
        log(f"Cards for an account that isn't on this laptop ({payload['game']}).")
        return False
    cards = [{"title": text(c.get("title"), 120), "text": text(c.get("text"), 400)}
             for c in payload["cards"][:10] if isinstance(c, dict)]
    for card, raw in zip(cards, payload["cards"][:10]):
        if isinstance(raw, dict) and raw.get("away") is True:
            card["away"] = True             # a card for another crew (0044)
    deal = {"game": payload["game"], "seq": payload["seq"], "codename": text(payload.get("codename"), 40),
            "color": text(payload.get("color"), 9), "cards": cards}
    if isinstance(payload.get("crew"), str):
        deal.update(crew=text(payload["crew"], 12), crew_name=text(payload.get("crew_name"), 30),
                    crew_color=text(payload.get("crew_color"), 9))
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    path = os.path.join(RUN_DIR, f"deal-{entry.pw_uid}.json")
    old = read_json(path)
    if old and old.get("game") == deal["game"] and old.get("seq", 0) > deal["seq"]:
        return False                      # an older deal arriving late
    fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(deal, handle)
    if os.geteuid() == 0:
        os.chown(path + ".new", entry.pw_uid, entry.pw_gid)
    os.chmod(path + ".new", 0o600)
    os.replace(path + ".new", path)
    log(f"Cards for {deal['codename']} written ({len(cards)}).")
    return True


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def handle_body(state, body, topic_event_time=None):
    """One ntfy message body from the game topic."""
    deal = False
    try:
        deal = json.loads(body).get("lab_target") == 1
    except (ValueError, AttributeError):
        return
    if deal:
        inner = open_targeted(body)
        payload = open_signed(inner) if inner else None
        if not payload or HOSTNAME not in [str(n).lower() for n in payload.get("laptops", [])]:
            return
        with state.lock:
            current = state.game
        if payload["type"] == "deal" and payload["game"] == current:
            write_deal(payload)
        elif payload["type"] == "post" and payload.get("crew"):          # a crew's own wall (0044)
            with state.lock:
                if state.apply(payload):
                    state.write()
        return
    payload = open_signed(body)
    if not payload or payload["type"] == "deal":
        return
    with state.lock:
        if state.apply(payload):
            state.write()


# ---------- sessions and windows ----------

def logged_in_users():
    result = subprocess.run(["/usr/bin/loginctl", "list-sessions", "--no-legend"],
                            capture_output=True, text=True, check=False)
    return sorted({parts[2] for parts in (line.split() for line in result.stdout.splitlines())
                   if len(parts) > 5 and parts[5] == "user"})


def is_admin(user):
    try:
        entry = pwd.getpwnam(user)
        sudo = grp.getgrnam("sudo")
    except KeyError:
        return False
    return user in sudo.gr_mem or entry.pw_gid == sudo.gr_gid


def run_as(user, command):
    result = subprocess.run(["/usr/bin/systemd-run", "--quiet", "--collect", f"--machine={user}@", "--user", *command],
                            capture_output=True, text=True, check=False)
    return result.returncode == 0


def action_dir():
    return os.path.join(RUN_DIR, "actions")


def prepare_dirs():
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    os.makedirs(action_dir(), exist_ok=True)
    os.chmod(action_dir(), 0o1733)


def read_action_file(path):
    """(owner account, action dict) from a dropped file, or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ACTION_BYTES:
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            action = json.loads(handle.read().decode("utf-8"))
        return pwd.getpwuid(info.st_uid).pw_name, action, info.st_mtime
    except (OSError, ValueError, KeyError, UnicodeDecodeError):
        return None
    finally:
        os.close(fd)


def make_action(state, user, kind, **fields):
    return dict({"v": 1, "game": state.game, "type": kind, "user": user, "laptop": HOSTNAME,
                 "sent": int(time.time()), "nonce": secrets.token_hex(6)}, **fields)


def collect_actions(state, outbox):
    """Dropped posts and guesses for the current, live game go to the outbox."""
    try:
        names = os.listdir(action_dir())
    except OSError:
        return
    found = []
    for name in names:
        path = os.path.join(action_dir(), name)
        result = read_action_file(path)
        try:
            os.unlink(path)
        except OSError:
            pass
        if result:
            found.append(result)
    for user, action, _mtime in sorted(found, key=lambda item: item[2]):
        if not isinstance(action, dict):
            continue
        with state.lock:
            if not state.live() or action.get("game") != state.game:
                continue
            lock_ids = {lock["id"] for lock in state.data["locks"]}
        if action.get("type") == "post" and isinstance(action.get("text"), str) and action["text"].strip():
            outbox.append(make_action(state, user, "post", text=action["text"][:200]))
        elif (action.get("type") == "guess" and action.get("lock") in lock_ids
              and isinstance(action.get("text"), str) and action["text"].strip()):
            outbox.append(make_action(state, user, "guess", lock=action["lock"], text=action["text"][:40]))


def sign_action(text_value):
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "action")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text_value)
        subprocess.run(["/usr/bin/ssh-keygen", "-Y", "sign", "-q", "-f", LAPTOP_KEY, "-n", NAMESPACE, path],
                       check=True, capture_output=True)
        with open(path + ".sig", encoding="utf-8") as handle:
            return handle.read()


def action_body(action):
    """Signed with this laptop's key, then encrypted to the teacher (as poll answers)."""
    text_value = json.dumps(action, sort_keys=True)
    with open(LAPTOP_KEY + ".pub", encoding="utf-8") as handle:
        public = handle.read().strip()
    envelope = json.dumps({"action": text_value, "sig": sign_action(text_value), "pubkey": public}).encode("utf-8")
    with open(TEACHER_KEY, "rb") as handle:
        teacher = serialization.load_pem_public_key(handle.read())
    secret = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    data = AESGCM(secret).encrypt(nonce, zlib.compress(envelope, 9), None)
    wrapped = teacher.encrypt(secret, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                   algorithm=hashes.SHA256(), label=None))
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")
    return json.dumps({"lab_game": 1, "key": b64(wrapped), "nonce": b64(nonce), "data": b64(data)}).encode("utf-8")


def post(servers, topic, body):
    error = RuntimeError("no server")
    for server in servers:
        try:
            request = urllib.request.Request(f"{server}/{topic}", data=body, method="POST",
                                             headers={"User-Agent": "lab-game/1"})
            with urllib.request.urlopen(request, timeout=20) as response:
                response.read()
            return server
        except Exception as failure:
            error = failure
    raise error


def send_actions(state, servers, topic, outbox):
    while outbox:
        action = outbox[0]
        with state.lock:
            if action["game"] != state.game or not state.live():
                outbox.pop(0)
                continue
        try:
            post(servers, topic, action_body(action))
            log(f"Sent {action['type']} from {action['user']}.")
            outbox.pop(0)
        except Exception as error:
            log(f"Action not sent yet ({error.__class__.__name__}).")
            return


class Sessions:
    """Opens the game window for each session once per game, and joins students."""

    def __init__(self, state):
        self.state = state
        self.opened = set()          # (game, user)
        self.joins = {}              # (game, user) -> [last sent, tries]

    def allowed(self, user, accounts, game):
        return accounts is None or account_tag(game, user) in accounts

    def tick(self, outbox, now=None):
        now = time.time() if now is None else now
        with self.state.lock:
            if not self.state.live(now):
                return
            game, accounts = self.state.game, self.state.data["accounts"]
        for user in logged_in_users():
            try:
                uid = pwd.getpwnam(user).pw_uid
            except KeyError:
                continue
            if not os.path.exists(f"/run/user/{uid}/bus"):
                continue
            admin = is_admin(user)
            if not admin and not self.allowed(user, accounts, game):
                continue
            key = (game, user)
            if key not in self.opened:
                self.opened.add(key)
                shown = run_as(user, ["/usr/bin/python3", "-I", WINDOW])
                log(f"Game {game}: window {'opened' if shown else 'NOT opened'} for {user}{' (big screen)' if admin else ''}.")
            if admin:
                continue
            deal = read_json(os.path.join(RUN_DIR, f"deal-{uid}.json"))
            if deal and deal.get("game") == game:
                continue
            last, tries = self.joins.get(key, (0, 0))
            if tries < JOIN_TRIES and now - last >= JOIN_RETRY_SECONDS:
                self.joins[key] = (now, tries + 1)
                outbox.append(make_action(self.state, user, "join"))


def worker(state, servers, action_topic, rounds=None):
    sessions = Sessions(state)
    outbox = []
    while rounds is None or rounds > 0:
        try:
            collect_actions(state, outbox)
            sessions.tick(outbox)
            send_actions(state, servers, action_topic, outbox)
        except Exception as error:
            log(f"Game worker: {error.__class__.__name__}: {error}")
        if rounds is not None:
            rounds -= 1
            continue
        time.sleep(TICK_SECONDS / 2)


# ---------- listening ----------

def listen_once(state, server, topic, since, until=None, on_time=None):
    url = f"{server}/{urllib.parse.quote(topic)}/json?" + urllib.parse.urlencode({"since": since})
    request = urllib.request.Request(url, headers={"User-Agent": "lab-game/1"})
    with urllib.request.urlopen(request, timeout=READ_TIMEOUT_SECONDS) as stream:
        log(f"Connected to {server}.")
        for raw_line in stream:
            if until is not None and time.time() >= until:
                return
            try:
                event = json.loads(raw_line)
            except ValueError:
                continue
            if event.get("event") != "message":
                continue
            if on_time:
                on_time(event.get("time"))
            handle_body(state, event.get("message", ""))


def healthy(server):
    try:
        request = urllib.request.Request(f"{server}/v1/health", headers={"User-Agent": "lab-game/1"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return bool(json.loads(response.read(2000)).get("healthy"))
    except Exception:
        return False


def main():
    servers, topic, action_topic = read_config()
    prepare_dirs()
    state = State()
    threading.Thread(target=worker, args=(state, servers, action_topic), daemon=True).start()
    last = {"time": None}
    index, delay = 0, 5

    def remember(value):
        if isinstance(value, int):
            last["time"] = value

    while True:
        since = str(last["time"] - 5) if last["time"] else CATCH_UP
        server = servers[index]
        until = time.time() + PRIMARY_RETRY_SECONDS if index > 0 else None
        try:
            listen_once(state, server, topic, since, until, remember)
            failed, delay = False, 5
        except Exception as error:
            log(f"Not connected to {server} ({error.__class__.__name__}).")
            failed = True
        if index > 0 and healthy(servers[0]):
            index = 0
            continue
        if failed:
            if index + 1 < len(servers):
                index += 1
                time.sleep(1)
            else:
                index = 0
                time.sleep(delay)
                delay = min(delay * 2, 60)
        else:
            time.sleep(1)


if __name__ == "__main__":
    main()
