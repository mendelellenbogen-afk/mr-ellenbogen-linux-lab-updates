#!/usr/bin/env python3
"""The Threshold (the class RPG) on a lab laptop: opens the game in Chrome
for each student when the teacher has a world running.

Every POLL_SECONDS, while a student is logged in, it asks the game server
(RPG_URL in /etc/lab-rpg/config, the teacher's computer through the lab
server) whether a world is open. For each student who hasn't had the game
opened in this session yet, it asks the server for a one-time sign-in link,
signed with this laptop's own key (the one in the lab inventory), and opens
the link in Chrome as that student. The server only answers for students of
the class that is playing; anyone else is left alone.

"The Threshold" in the app menu drops a request in /run/lab-rpg/requests
(the file's owner says who asked), and the game opens again for them.

Admin accounts are skipped. Nothing is sent while no world is open.
"""

import base64
import json
import os
import pwd
import grp
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

CONFIG_FILE = os.environ.get("LAB_RPG_CONFIG", "/etc/lab-rpg/config")
RUN_DIR = os.environ.get("LAB_RPG_RUN_DIR", "/run/lab-rpg")
LAPTOP_KEY = os.environ.get("LAB_RPG_LAPTOP_KEY", "/var/lib/lab-inventory/laptop-key")
HOSTNAME = (os.environ.get("LAB_RPG_HOSTNAME") or socket.gethostname()).lower()
ALLOW_HTTP = os.environ.get("LAB_RPG_ALLOW_HTTP") == "1"      # tests with a local server only
BROWSER = os.environ.get("LAB_RPG_BROWSER", "/usr/bin/google-chrome")

NAMESPACE = "lab-rpg"
POLL_SECONDS = 20              # how often to ask whether a world is open
TICK_SECONDS = 2               # how often to look for app-menu requests
REQUEST_SECONDS = 10            # one menu request per student per 10 s
MAX_REQUEST_BYTES = 256


def log(message):
    print(message, flush=True)


def rpg_url():
    """The game's address from the config, or None."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key.strip() == "RPG_URL":
                    value = value.strip().rstrip("/")
                    if value.startswith("https://") or (ALLOW_HTTP and value.startswith("http://")):
                        return value
    except OSError:
        pass
    return None


# ---------- who is logged in ----------

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


def has_desktop(user):
    try:
        return os.path.exists(f"/run/user/{pwd.getpwnam(user).pw_uid}/bus")
    except KeyError:
        return False


def students():
    return [u for u in logged_in_users() if not is_admin(u) and has_desktop(u)]


# ---------- talking to the game server ----------

def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read(4096))


def open_session(base):
    """The running world's session id, or None (no world, or the server is off)."""
    try:
        answer = fetch(base + "/api/open")
    except (OSError, ValueError, urllib.error.URLError):
        return None
    session = answer.get("session") if answer.get("open") else None
    return session if isinstance(session, str) and 0 < len(session) <= 64 else None


def sign(text_value):
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "request")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text_value)
        subprocess.run(["/usr/bin/ssh-keygen", "-Y", "sign", "-q", "-f", LAPTOP_KEY, "-n", NAMESPACE, path],
                       check=True, capture_output=True)
        with open(path + ".sig", encoding="utf-8") as handle:
            return handle.read()


def sign_in_link(base, session, user):
    """A one-time game link for this student, or None (with the reason logged)."""
    request = json.dumps({"account": user, "laptop": HOSTNAME, "session": session,
                          "time": time.time(), "nonce": os.urandom(12).hex()})
    with open(LAPTOP_KEY + ".pub", encoding="utf-8") as handle:
        public = handle.read().strip()
    envelope = json.dumps({"request": request, "sig": sign(request), "pubkey": public})
    try:
        answer = fetch(base + "/api/signin", {"X-Lab-Signin": base64.b64encode(envelope.encode()).decode()})
    except urllib.error.HTTPError as error:
        try:
            reason = json.loads(error.read(512)).get("error", error.code)
        except ValueError:
            reason = error.code
        log(f"No game link for {user}: {reason}.")
        return None
    except (OSError, ValueError, urllib.error.URLError) as error:
        log(f"No game link for {user}: {error}.")
        return None
    token = answer.get("token")
    if not isinstance(token, str) or not token.replace("-", "").replace("_", "").isalnum() or len(token) > 64:
        return None
    return f"{base}/?t={token}"


def run_as(user, command):
    """Start a program in the student's own desktop session."""
    result = subprocess.run(["/usr/bin/systemd-run", "--quiet", "--collect", f"--machine={user}@", "--user",
                             *command], capture_output=True, text=True, check=False)
    return result.returncode == 0


def open_game(user, link):
    return run_as(user, [BROWSER, f"--app={link}", "--new-window"])


# ---------- the app-menu launcher ----------

def requests_dir():
    return os.path.join(RUN_DIR, "requests")


def prepare_dirs():
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    os.makedirs(requests_dir(), exist_ok=True)
    os.chmod(requests_dir(), 0o1733)      # anyone may drop a file, nobody can read or remove others'


def menu_requests():
    """Users who asked through the app menu (each file's owner), files removed."""
    asked = set()
    for name in os.listdir(requests_dir()):
        path = os.path.join(requests_dir(), name)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:                    # a symlink or something odd: just remove it
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        try:
            info = os.fstat(fd)
            if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_REQUEST_BYTES:
                asked.add(pwd.getpwuid(info.st_uid).pw_name)
        except (OSError, KeyError):
            pass
        finally:
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass
    return asked


# ---------- the loop ----------

class Agent:
    def __init__(self):
        self.opened = {}       # user -> session the game was opened for
        self.asked = {}        # user -> last menu request handled
        self.polled = 0

    def tick(self, now=None):
        now = time.time() if now is None else now
        asked = menu_requests()
        if not asked and now - self.polled < POLL_SECONDS:
            return
        self.polled = now
        users = students()
        if not users:
            return
        base = rpg_url()
        session = open_session(base) if base else None
        if not session:
            return
        for user in users:
            again = user in asked and now - self.asked.get(user, 0) >= REQUEST_SECONDS
            if self.opened.get(user) == session and not again:
                continue
            if again:
                self.asked[user] = now
            self.opened[user] = session          # once per session, even if the server said no
            link = sign_in_link(base, session, user)
            if link:
                log(f"The Threshold {'opened' if open_game(user, link) else 'NOT opened'} for {user}.")


def main():
    if not os.path.exists(LAPTOP_KEY):
        log("No laptop key yet (the inventory report makes it); waiting.")
    prepare_dirs()
    agent = Agent()
    while True:
        try:
            if os.path.exists(LAPTOP_KEY):
                agent.tick()
        except Exception as error:      # never let one bad round stop the service
            log(f"Round failed: {error}")
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
