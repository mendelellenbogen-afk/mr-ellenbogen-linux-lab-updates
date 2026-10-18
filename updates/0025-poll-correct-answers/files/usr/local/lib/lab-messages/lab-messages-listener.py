#!/usr/bin/env python3
"""Live messages: listen on the lab's ntfy.sh topic and pop up signed messages
on every desktop that is logged in right now.

Rules (from the teacher):
  * Only laptops logged in when a message is sent show it. Nothing is queued:
    a laptop that connects later never shows an old message.
  * Only messages signed with the lab key are shown (namespace "lab-message",
    key pinned in /etc/lab-updater/allowed_signers). Others are ignored.
  * Admin-only messages (update 0019) are shown only to sudo-group users.
    They come on ADMIN_TOPIC and their signed payload says "to": "admins";
    either one is enough to keep them away from students.
  * Open a link (update 0020): a payload with "open": "https://..." opens that
    web page in each user's default browser. Only http/https links; anything
    else is ignored. The pop-up is shown too only when the message has text.
  * Full screen and sound (update 0021): "fullscreen": true opens the link
    full screen in a separate Firefox kiosk window that may autoplay with
    sound; "volume": 0-100 unmutes and sets the volume; "close": true closes
    that full-screen window. All done by lab-present in the user's session.
  * Targeted messages (update 0023), on TARGET_TOPIC, for particular laptops
    or students. Each is encrypted to the target laptops' own message keys
    (X25519, /var/lib/lab-inventory/message-key; the public halves reach the
    teacher through the lab inventory). Inside is a normal signed message
    whose payload names the targets: "to_laptops": [names] and optionally
    "to_students": [student IDs] (then only those students' sessions see it).
    Other laptops can't read it; the signature makes the target list trusted.
  * Class polls (update 0024), on POLL_TOPIC: a signed payload with
    "poll": {"id", "question", "options"} opens poll-window.py in every
    logged-in session. The student picks an option (and may change it); the
    window drops the choice in ANSWER_DIR (sticky, like /tmp), and this
    service, as root, takes the account name from the file's owner, signs the
    answer with this laptop's own key (lab inventory, namespace "lab-poll"),
    encrypts it to the teacher's key and posts it on POLL_ANSWER_TOPIC.
    "poll_close": {"id", "question", "options", "counts", "answered"} ends it:
    every window turns into the results (opened if it was closed).
  * Correct answers (update 0025): "poll_close" may carry "correct": [option
    indexes] (one or more). They are never sent with the poll itself, so
    nobody can read them early; the results then say "Correct!" or
    "Not quite" to each student. Without it the poll is a plain opinion poll.

Wire format (ntfy message body):
  {"payload": "<JSON text>", "sig": "<ssh-keygen -Y sign output>"}
payload: {"v": 1, "id": "...", "sent": <unix time>, "title": ..., "text": ..., "code": ...,
          "to": "admins" (optional), "open": "https://..." (optional),
          "fullscreen": true, "volume": 0-100, "close": true (optional)}
"""

import base64
import grp
import json
import os
import pwd
import socket
import subprocess
import stat
import tempfile
import threading
import time
import zlib
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONFIG_FILE = os.environ.get("LAB_MESSAGES_CONFIG", "/etc/lab-messages/config")
ALLOWED_SIGNERS = os.environ.get("LAB_MESSAGES_SIGNERS", "/etc/lab-updater/allowed_signers")
WINDOW = os.environ.get("LAB_MESSAGES_WINDOW", "/usr/local/lib/lab-messages/message-window.py")
MESSAGE_KEY = os.environ.get("LAB_MESSAGES_KEY", "/var/lib/lab-inventory/message-key")
HOSTNAME = os.environ.get("LAB_MESSAGES_HOSTNAME") or socket.gethostname()
PRESENT = os.environ.get("LAB_MESSAGES_PRESENT", "/usr/local/lib/lab-messages/lab-present")
RUN_DIR = os.environ.get("LAB_MESSAGES_RUN_DIR", "/run/lab-messages")
POLL_WINDOW = os.environ.get("LAB_MESSAGES_POLL_WINDOW", "/usr/local/lib/lab-messages/poll-window.py")
LAPTOP_KEY = os.environ.get("LAB_MESSAGES_LAPTOP_KEY", "/var/lib/lab-inventory/laptop-key")
TEACHER_KEY = os.environ.get("LAB_MESSAGES_TEACHER_KEY", "/etc/lab-inventory/teacher-key.pub.pem")

NAMESPACE = "lab-message"
MAX_LINK_LENGTH = 2000
MAX_AGE_SECONDS = 120          # older than this = "sent while this laptop wasn't listening"
MAX_CLOCK_AHEAD_SECONDS = 60
RECONNECT_CATCHUP_SECONDS = 90  # after a short network blip, fetch what was missed
READ_TIMEOUT_SECONDS = 90       # ntfy sends a keepalive every ~45 s
POLL_NAMESPACE = "lab-poll"
MAX_POLL_OPTIONS = 6
MAX_POLL_SECONDS = 3 * 3600     # a poll never left open is forgotten after this


def log(message):
    print(message, flush=True)


def read_config():
    config = {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
        for line in config_file:
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                config[key.strip()] = value.strip()
    return (config["SERVER"].rstrip("/"), config["TOPIC"], config.get("ADMIN_TOPIC", ""),
            config.get("TARGET_TOPIC", ""))


def read_poll_config():
    """(POLL_TOPIC, POLL_ANSWER_TOPIC); empty strings if polls aren't set up."""
    config = {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
        for line in config_file:
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                config[key.strip()] = value.strip()
    return config.get("POLL_TOPIC", ""), config.get("POLL_ANSWER_TOPIC", "")


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


def open_targeted(body):
    """The signed message inside a targeted envelope, if it is addressed to this
    laptop and decrypts with its key; else None (most laptops: not for them)."""
    try:
        outer = json.loads(body)
        mine = outer["to"].get(HOSTNAME)
        if outer.get("lab_target") != 1 or not mine:
            return None
        raw = lambda text: base64.b64decode(text)
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
        log(f"Ignored a targeted message this laptop can't open ({error.__class__.__name__}).")
        return None


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


def is_admin(user):
    try:
        entry = pwd.getpwnam(user)
        sudo = grp.getgrnam("sudo")
    except KeyError:
        return False
    return user in sudo.gr_mem or entry.pw_gid == sudo.gr_gid


def safe_link(link):
    """The link if it is a plain http(s) web address, else None."""
    if not isinstance(link, str) or not link or len(link) > MAX_LINK_LENGTH:
        return None
    if any(ord(c) <= 32 or ord(c) == 127 for c in link):
        return None
    try:
        parts = urllib.parse.urlsplit(link)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return link


def safe_volume(volume):
    """An int 0-100, else None."""
    if isinstance(volume, int) and not isinstance(volume, bool) and 0 <= volume <= 100:
        return volume
    return None


def run_as(user, command):
    """Run a command in the user's desktop session. True if it started."""
    result = subprocess.run(
        # KillMode=process: a browser started by xdg-open outlives xdg-open.
        ["/usr/bin/systemd-run", "--quiet", "--collect", "--property=KillMode=process",
         f"--machine={user}@", "--user", *command],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def show(message, admins_only=False, students=None):
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
    opened = 0
    link = safe_link(message.get("open"))
    if message.get("open") and not link:
        log(f"Message {message['id']}: ignored a link that isn't a plain http(s) address.")
    fullscreen = message.get("fullscreen") is True
    close = message.get("close") is True
    volume = safe_volume(message.get("volume"))
    present = []        # lab-present arguments besides the link
    if volume is not None:
        present += ["--volume", str(volume)]
    if close:
        present.append("--close")
    always_popup = not (link or present) or bool(message.get("text"))

    if students is not None:
        wanted = {"tdsb-" + str(student).strip().lower() for student in students}

    for user in logged_in_users():
        if admins_only and not is_admin(user):
            continue

        if students is not None and user.lower() not in wanted:
            continue

        try:
            uid = pwd.getpwnam(user).pw_uid
        except KeyError:
            continue

        if not os.path.exists(f"/run/user/{uid}/bus"):
            continue

        popup = always_popup
        if link and fullscreen:
            if run_as(user, [PRESENT, *present, link]):
                opened += 1
            else:
                popup = True    # couldn't open it: show the pop-up instead
        else:
            if present:
                run_as(user, [PRESENT, *present])
            if link:
                if run_as(user, ["/usr/bin/xdg-open", link]):
                    opened += 1
                else:
                    popup = True

        if not popup:
            continue

        if run_as(user, ["/usr/bin/python3", WINDOW, path]):
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

    audience = "admin " if admins_only else ""
    log(f"Showed message {message['id']} ({message.get('title', '')!r}) to {shown} {audience}user(s).")
    if link:
        how = "full screen " if fullscreen else ""
        log(f"Opened {link} {how}for {opened} {audience}user(s).")
    if present:
        log(f"Ran lab-present {' '.join(present)} for the {audience}user(s).")


# ---------- class polls (update 0024) ----------

POLLS = {}                    # poll id -> {"question", "options", "closed", "started"}
POLLS_LOCK = threading.Lock()


def answer_dir():
    return os.path.join(RUN_DIR, "poll-answers")


def prepare_answer_dir():
    """Sticky and writable by everyone, like /tmp: a student can drop an answer
    file but can't list, change or delete anyone else's."""
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    os.makedirs(answer_dir(), exist_ok=True)
    os.chmod(answer_dir(), 0o1733)


def poll_text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def valid_poll(poll):
    """(id, question, options) from a poll dict, or None."""
    if not isinstance(poll, dict):
        return None
    poll_id = poll.get("id")
    question = poll_text(poll.get("question"), 500)
    options = poll.get("options")
    if not (isinstance(poll_id, str) and 0 < len(poll_id) <= 40
            and all(c.isalnum() or c == "-" for c in poll_id)):
        return None
    if not question or not isinstance(options, list) or not 2 <= len(options) <= MAX_POLL_OPTIONS:
        return None
    options = [poll_text(option, 120) for option in options]
    if not all(options):
        return None
    return poll_id, question, options


def poll_file(poll_id):
    return os.path.join(RUN_DIR, f"poll-{poll_id}.json")


def write_poll_file(poll_id, data):
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    path = poll_file(poll_id)
    with open(path + ".new", "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.chmod(path + ".new", 0o644)
    os.replace(path + ".new", path)
    return path


def open_poll_windows(path):
    """Run the poll window in every desktop session. A window already open for
    this poll just refreshes (it is a single-instance app per session)."""
    shown = 0
    for user in logged_in_users():
        try:
            uid = pwd.getpwnam(user).pw_uid
        except KeyError:
            continue
        if not os.path.exists(f"/run/user/{uid}/bus"):
            continue
        shown += run_as(user, ["/usr/bin/python3", POLL_WINDOW, path])
    return shown


def handle_poll(message):
    if "poll" in message:
        checked = valid_poll(message["poll"])
        if not checked:
            log(f"Ignored poll message {message['id']}: bad poll.")
            return
        poll_id, question, options = checked
        with POLLS_LOCK:
            POLLS[poll_id] = {"question": question, "options": options, "closed": False,
                              "started": time.time()}
        path = write_poll_file(poll_id, {"id": poll_id, "question": question, "options": options,
                                         "closed": False})
        log(f"Poll {poll_id}: shown to {open_poll_windows(path)} user(s).")
        return

    close = message["poll_close"]
    checked = valid_poll(close)
    counts = close.get("counts") if checked else None
    answered = close.get("answered") if checked else None
    if (not checked or not isinstance(counts, list) or len(counts) != len(checked[2])
            or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts)
            or not isinstance(answered, int) or isinstance(answered, bool) or answered < 0):
        log(f"Ignored poll message {message['id']}: bad results.")
        return
    poll_id, question, options = checked
    correct = close.get("correct", [])
    if (not isinstance(correct, list) or len(set(correct)) != len(correct)
            or not all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n < len(options) for n in correct)):
        log(f"Ignored poll message {message['id']}: bad correct answers.")
        return
    with POLLS_LOCK:
        POLLS[poll_id] = {"question": question, "options": options, "closed": True,
                          "started": POLLS.get(poll_id, {}).get("started", time.time())}
    path = write_poll_file(poll_id, {"id": poll_id, "question": question, "options": options,
                                     "closed": True, "counts": counts, "answered": answered,
                                     "correct": sorted(correct)})
    log(f"Poll {poll_id} closed: results shown to {open_poll_windows(path)} user(s).")


def read_answer_file(path):
    """(owner account, answer dict) from a dropped answer file, or None. The
    account comes from who owns the file, never from what it says."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024:
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            answer = json.loads(handle.read().decode("utf-8"))
        return pwd.getpwuid(info.st_uid).pw_name, answer, info.st_mtime
    except (OSError, ValueError, KeyError, UnicodeDecodeError):
        return None
    finally:
        os.close(fd)


def collect_answers(pending):
    """Move dropped answer files into pending {(poll, user): answer}, keeping the
    newest per student; only for polls that are open on this laptop."""
    try:
        names = os.listdir(answer_dir())
    except OSError:
        return
    found = []
    for name in names:
        path = os.path.join(answer_dir(), name)
        result = read_answer_file(path)
        try:
            os.unlink(path)
        except OSError:
            pass
        if result:
            found.append(result)
    for user, answer, mtime in sorted(found, key=lambda item: item[2]):
        if not isinstance(answer, dict):
            continue
        poll_id, choice = answer.get("poll"), answer.get("choice")
        with POLLS_LOCK:
            poll = POLLS.get(poll_id)
            if not poll or poll["closed"]:
                continue
            count = len(poll["options"])
        if isinstance(choice, int) and not isinstance(choice, bool) and 0 <= choice < count:
            pending[(poll_id, user)] = {"v": 1, "poll": poll_id, "choice": choice, "user": user,
                                        "laptop": HOSTNAME, "sent": int(time.time())}


def sign_answer(text):
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "answer")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        subprocess.run(["/usr/bin/ssh-keygen", "-Y", "sign", "-q", "-f", LAPTOP_KEY,
                        "-n", POLL_NAMESPACE, path], check=True, capture_output=True)
        with open(path + ".sig", "r", encoding="utf-8") as handle:
            return handle.read()


def encrypt_answer(plaintext):
    """Same scheme as the inventory reports: RSA-OAEP wraps an AES-GCM key."""
    with open(TEACHER_KEY, "rb") as handle:
        teacher = serialization.load_pem_public_key(handle.read())
    secret = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    data = AESGCM(secret).encrypt(nonce, zlib.compress(plaintext, 9), None)
    wrapped = teacher.encrypt(secret, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                   algorithm=hashes.SHA256(), label=None))
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")
    return json.dumps({"lab_poll": 1, "key": b64(wrapped), "nonce": b64(nonce), "data": b64(data)})


def answer_body(answer):
    text = json.dumps(answer, sort_keys=True)
    with open(LAPTOP_KEY + ".pub", "r", encoding="utf-8") as handle:
        public = handle.read().strip()
    envelope = json.dumps({"answer": text, "sig": sign_answer(text), "pubkey": public})
    return encrypt_answer(envelope.encode("utf-8"))


def send_answers(server, topic, pending):
    for key in list(pending):
        with POLLS_LOCK:
            poll = POLLS.get(key[0])
            still_open = bool(poll) and not poll["closed"]
        if not still_open:
            pending.pop(key)        # too late: the poll closed before it went out
            continue
        try:
            body = answer_body(pending[key]).encode("utf-8")
            request = urllib.request.Request(f"{server}/{topic}", data=body, method="POST",
                                             headers={"User-Agent": "lab-poll/1"})
            with urllib.request.urlopen(request, timeout=20) as response:
                response.read()
            log(f"Poll {key[0]}: sent an answer from {key[1]}.")
            pending.pop(key)
        except Exception as error:   # offline for a moment: try again next round
            log(f"Poll {key[0]}: answer not sent yet ({error.__class__.__name__}).")


def forget_old_polls():
    with POLLS_LOCK:
        for poll_id in [p for p, poll in POLLS.items() if time.time() - poll["started"] > MAX_POLL_SECONDS]:
            POLLS.pop(poll_id)
            try:
                os.unlink(poll_file(poll_id))
            except OSError:
                pass


def answer_loop(server, topic, rounds=None):
    pending = {}
    while rounds is None or rounds > 0:
        try:
            collect_answers(pending)
            send_answers(server, topic, pending)
            forget_old_polls()
        except Exception as error:   # never let the answer sender die
            log(f"Poll answers: {error.__class__.__name__}: {error}")
        if rounds is not None:
            rounds -= 1
            continue
        time.sleep(1)


def listen_once(server, topics, admin_topic, since, seen, on_event_id, target_topic="", poll_topic=""):
    url = f"{server}/{','.join(urllib.parse.quote(topic) for topic in topics)}/json"
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

            on_event_id(event.get("time"))
            targeted = bool(target_topic) and event.get("topic") == target_topic
            body = event.get("message", "")
            if targeted:
                body = open_targeted(body)
                if body is None:
                    continue
            message = parse(body, seen)

            if not message:
                continue
            if "poll" in message or "poll_close" in message:
                if not targeted and poll_topic and event.get("topic") == poll_topic:
                    handle_poll(message)
                continue
            if poll_topic and event.get("topic") == poll_topic:
                continue
            admins_only = message.get("to") == "admins" or (
                bool(admin_topic) and event.get("topic") == admin_topic)
            if targeted or "to_laptops" in message:
                laptops = message.get("to_laptops")
                if not isinstance(laptops, list) or HOSTNAME not in laptops:
                    log(f"Ignored message {message['id']}: not addressed to {HOSTNAME}.")
                    continue
                students = message.get("to_students")
                show(message, admins_only, students if isinstance(students, list) else None)
            else:
                show(message, admins_only)


def main():
    server, topic, admin_topic, target_topic = read_config()
    poll_topic, answer_topic = read_poll_config()
    topics = [topic] + [t for t in (admin_topic, target_topic, poll_topic) if t]
    if poll_topic and answer_topic:
        prepare_answer_dir()
        threading.Thread(target=answer_loop, args=(server, answer_topic), daemon=True).start()
    seen = set()
    state = {"last_time": None, "lost_at": None}
    delay = 5

    def remember(event_time):
        state["last_time"] = event_time

    while True:
        since = None
        # A unix time works across both topics; "seen" drops repeats.
        if state["last_time"] and state["lost_at"] and time.time() - state["lost_at"] < RECONNECT_CATCHUP_SECONDS:
            since = state["last_time"]

        try:
            listen_once(server, topics, admin_topic, since, seen, remember, target_topic, poll_topic)
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
