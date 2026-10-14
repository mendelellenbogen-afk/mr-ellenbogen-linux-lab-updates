#!/usr/bin/env python3
"""Live messages: listen on the lab's ntfy.sh topic and pop up signed messages
on every desktop that is logged in right now.

Rules (from the teacher):
  * Only laptops logged in when a message is sent show it. Nothing is queued:
    a laptop that connects later never shows an old message.
  * Only messages signed with the lab key are shown (namespace "lab-message",
    key pinned in /etc/lab-updater/allowed_signers). Others are ignored.

Wire format (ntfy message body):
  {"payload": "<JSON text>", "sig": "<ssh-keygen -Y sign output>"}
payload: {"v": 1, "id": "...", "sent": <unix time>, "title": ..., "text": ..., "code": ...}
"""

import json
import os
import pwd
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

CONFIG_FILE = os.environ.get("LAB_MESSAGES_CONFIG", "/etc/lab-messages/config")
ALLOWED_SIGNERS = os.environ.get("LAB_MESSAGES_SIGNERS", "/etc/lab-updater/allowed_signers")
WINDOW = os.environ.get("LAB_MESSAGES_WINDOW", "/usr/local/lib/lab-messages/message-window.py")
RUN_DIR = os.environ.get("LAB_MESSAGES_RUN_DIR", "/run/lab-messages")

NAMESPACE = "lab-message"
MAX_AGE_SECONDS = 120          # older than this = "sent while this laptop wasn't listening"
MAX_CLOCK_AHEAD_SECONDS = 60
RECONNECT_CATCHUP_SECONDS = 90  # after a short network blip, fetch what was missed
READ_TIMEOUT_SECONDS = 90       # ntfy sends a keepalive every ~45 s


def log(message):
    print(message, flush=True)


def read_config():
    config = {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
        for line in config_file:
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                config[key.strip()] = value.strip()
    return config["SERVER"].rstrip("/"), config["TOPIC"]


def principal():
    with open(ALLOWED_SIGNERS, "r", encoding="utf-8") as signers:
        for line in signers:
            if line.strip() and not line.startswith("#"):
                return line.split()[0]
    raise RuntimeError("no trusted key")


def verify(payload_text, signature):
    with tempfile.NamedTemporaryFile("w", suffix=".sig", delete=True) as sig_file:
        sig_file.write(signature)
        sig_file.flush()
        result = subprocess.run(
            ["/usr/bin/ssh-keygen", "-Y", "verify", "-f", ALLOWED_SIGNERS,
             "-I", principal(), "-n", NAMESPACE, "-s", sig_file.name],
            input=payload_text.encode("utf-8"),
            capture_output=True,
        )
    return result.returncode == 0


def parse(body, seen, now=None):
    """Return the message dict to show, or None (with the reason logged)."""
    now = time.time() if now is None else now

    try:
        envelope = json.loads(body)
        payload_text = envelope["payload"]
        signature = envelope["sig"]
    except (ValueError, KeyError, TypeError):
        log("Ignored a message that isn't in the lab format.")
        return None

    if not verify(payload_text, signature):
        log("Ignored a message that isn't signed by the lab key.")
        return None

    try:
        message = json.loads(payload_text)
        message_id = str(message["id"])
        sent = float(message["sent"])
    except (ValueError, KeyError, TypeError):
        log("Ignored a signed message with a bad payload.")
        return None

    if message_id in seen:
        return None

    if now - sent > MAX_AGE_SECONDS or sent - now > MAX_CLOCK_AHEAD_SECONDS:
        log(f"Ignored message {message_id}: sent {int(now - sent)} s ago (too old or clock mismatch).")
        return None

    seen.add(message_id)
    return message


def logged_in_users():
    # loginctl columns: SESSION UID USER SEAT LEADER CLASS TTY IDLE SINCE
    result = subprocess.run(
        ["/usr/bin/loginctl", "list-sessions", "--no-legend"],
        capture_output=True, text=True, check=False,
    )
    users = sorted({
        parts[2] for parts in (line.split() for line in result.stdout.splitlines())
        if len(parts) > 5 and parts[5] == "user"
    })
    return users


def show(message):
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    path = os.path.join(RUN_DIR, f"{''.join(c for c in message['id'] if c.isalnum())}.json")

    with open(path, "w", encoding="utf-8") as message_file:
        json.dump({
            "title": message.get("title", "Message"),
            "text": message.get("text", ""),
            "code": message.get("code", ""),
        }, message_file)
    os.chmod(path, 0o644)

    shown = 0

    for user in logged_in_users():
        try:
            uid = pwd.getpwnam(user).pw_uid
        except KeyError:
            continue

        if not os.path.exists(f"/run/user/{uid}/bus"):
            continue

        result = subprocess.run(
            ["/usr/bin/systemd-run", "--quiet", "--collect", f"--machine={user}@", "--user",
             "/usr/bin/python3", WINDOW, path],
            capture_output=True, text=True, check=False,
        )

        if result.returncode == 0:
            shown += 1
        else:
            fallback = subprocess.run(
                ["/usr/sbin/runuser", "-u", user, "--", "env",
                 f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                 "/usr/bin/notify-send", message.get("title", "Message"),
                 message.get("text", "") or message.get("code", "")],
                capture_output=True, check=False,
            )
            shown += fallback.returncode == 0

    log(f"Showed message {message['id']} ({message.get('title', '')!r}) to {shown} user(s).")


def listen_once(server, topic, since, seen, on_event_id):
    url = f"{server}/{urllib.parse.quote(topic)}/json"
    if since:
        url += "?" + urllib.parse.urlencode({"since": since})

    request = urllib.request.Request(url, headers={"User-Agent": "lab-messages/1"})

    with urllib.request.urlopen(request, timeout=READ_TIMEOUT_SECONDS) as stream:
        log(f"Connected to {server}.")
        for raw_line in stream:
            try:
                event = json.loads(raw_line)
            except ValueError:
                continue

            if event.get("event") != "message":
                continue

            on_event_id(event.get("id"))
            message = parse(event.get("message", ""), seen)

            if message:
                show(message)


def main():
    server, topic = read_config()
    seen = set()
    state = {"last_id": None, "lost_at": None}
    delay = 5

    def remember(event_id):
        state["last_id"] = event_id

    while True:
        since = None
        if state["last_id"] and state["lost_at"] and time.time() - state["lost_at"] < RECONNECT_CATCHUP_SECONDS:
            since = state["last_id"]

        try:
            listen_once(server, topic, since, seen, remember)
            delay = 5
        except Exception as error:
            log(f"Not connected ({error.__class__.__name__}); retrying in {delay} s.")

        state["lost_at"] = time.time()
        time.sleep(delay)
        delay = min(delay * 2, 60)

        if len(seen) > 500:
            seen.clear()


if __name__ == "__main__":
    main()
