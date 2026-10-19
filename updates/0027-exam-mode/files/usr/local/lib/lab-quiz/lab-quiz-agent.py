#!/usr/bin/env python3
"""Lab quizzes / exam mode (update 0027): the laptop side. Runs as root
(lab-quiz.service), separate from the live-messages listener.

The teacher's choices (2026-10-18):
  * The teacher starts a quiz from their computer (tools/lab-quiz start) and
    ends it by hand; there is no timer. One student can be let to continue
    ("except"), and a quiz can be given again later (a new "sitting").
  * Each student gets their own version (context, numbers, question order).
  * During the quiz: internet blocked except the hand-in channel, other apps
    closed, USB sticks blocked. Answers are saved every few seconds.
  * Run button only where the teacher put one.

Messages (on QUIZ_TOPIC, signed with the lab key like live messages):
  {"quiz_start": {"sitting", "title", "total", "url", "sha256", "key",
                  "to_accounts": [..] or null, "to_laptops": [..] or null}}
      url = an ntfy attachment holding the quiz (AES-GCM with "key", zlib JSON:
      the student half of every version, no answers). Only sessions of the
      listed accounts (else: every non-admin account) on the listed laptops
      (else: all) take the quiz.
  {"quiz_end": {"sitting", "except": [accounts]}}   hand in everyone else's answers
  {"quiz_resend": {"sitting"}}                      send stored hand-ins again
Quiz messages count for MAX_SITTING_SECONDS (students log in late, so the
agent fetches the last hours from ntfy whenever it connects).

Hand-in: the window saves answers in ~/.local/state/lab-quiz/<sitting>.json
and drops {"sitting"} in /run/lab-quiz/submit (sticky, like /tmp). This agent
takes the account from the drop file's owner, reads that student's saved
answers, signs them with the laptop key (lab inventory, namespace
"lab-quiz"), encrypts them to the teacher's key, keeps a copy in
/var/lib/lab-quiz and posts them on QUIZ_ANSWER_TOPIC (retried until sent).

Lockdown (while any targeted student on this laptop hasn't handed in):
  * nftables table "inet labquiz": outgoing traffic only to the ntfy server
    (plus DNS, DHCP, ICMP); removed when the last student hands in, and at
    start-up when no quiz is active (so a crash never leaves it in place).
  * USB: mass-storage and camera/phone (MTP) interfaces are deauthorised,
    new ones too (a udev rule in /run); restored afterwards.
  * Apps: every launched app in the student's session (app-*, dbus-*, snap
    scopes in app.slice) is closed every 2 s; session services are left alone.
    The quiz window runs in session.slice and is restarted if it dies.
    GNOME's Alt+F2 command box is switched off for the student meanwhile.

Testing aids: LAB_QUIZ_* environment variables override paths and commands.
"""

import base64
import glob
import grp
import hashlib
import json
import os
import pwd
import re
import shutil
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
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENV = os.environ.get
CONFIG_FILE = ENV("LAB_QUIZ_CONFIG", "/etc/lab-quiz/config")
ALLOWED_SIGNERS = ENV("LAB_QUIZ_SIGNERS", "/etc/lab-updater/allowed_signers")
STATE_DIR = ENV("LAB_QUIZ_STATE", "/var/lib/lab-quiz")
RUN_DIR = ENV("LAB_QUIZ_RUN", "/run/lab-quiz")
WINDOW = ENV("LAB_QUIZ_WINDOW", "/usr/local/lib/lab-quiz/quiz-window.py")
LAPTOP_KEY = ENV("LAB_QUIZ_LAPTOP_KEY", "/var/lib/lab-inventory/laptop-key")
TEACHER_KEY = ENV("LAB_QUIZ_TEACHER_KEY", "/etc/lab-inventory/teacher-key.pub.pem")
HOSTNAME = ENV("LAB_QUIZ_HOSTNAME") or socket.gethostname()
CGROUP_ROOT = ENV("LAB_QUIZ_CGROUP", "/sys/fs/cgroup")
USB_DEVICES = ENV("LAB_QUIZ_USB", "/sys/bus/usb/devices")
UDEV_RULE = ENV("LAB_QUIZ_UDEV_RULE", "/run/udev/rules.d/70-lab-quiz-usb.rules")
NFT = ENV("LAB_QUIZ_NFT", "/usr/sbin/nft")
LOGINCTL = ENV("LAB_QUIZ_LOGINCTL", "/usr/bin/loginctl")
SYSTEMCTL = ENV("LAB_QUIZ_SYSTEMCTL", "/usr/bin/systemctl")
SYSTEMD_RUN = ENV("LAB_QUIZ_SYSTEMD_RUN", "/usr/bin/systemd-run")
UDEVADM = ENV("LAB_QUIZ_UDEVADM", "/usr/bin/udevadm")

MESSAGE_NAMESPACE = "lab-message"       # the teacher signs with the lab key, like live messages
ANSWER_NAMESPACE = "lab-quiz"
MAX_SITTING_SECONDS = 5 * 3600
MAX_CLOCK_AHEAD_SECONDS = 120
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_SAVE_BYTES = 512 * 1024
READ_TIMEOUT_SECONDS = 90
USB_BLOCKED_CLASSES = {"08", "06"}      # mass storage; still image (cameras, phones over MTP/PTP)
SITTING_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
ACCOUNT_RE = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,63}$")
LOCK = threading.RLock()


def log(message):
    print(message, flush=True)


def read_config():
    config = {}
    with open(CONFIG_FILE, encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                config[key.strip()] = value.strip()
    return config["SERVER"].rstrip("/"), config["QUIZ_TOPIC"], config["QUIZ_ANSWER_TOPIC"]


# ---------------------------------------------------------------- teacher messages

def principal():
    with open(ALLOWED_SIGNERS, encoding="utf-8") as handle:
        for line in handle:
            if line.strip() and not line.startswith("#"):
                return line.split()[0]
    raise RuntimeError("no trusted key")


def verify(payload_text, signature):
    with tempfile.NamedTemporaryFile("w", suffix=".sig") as sig_file:
        sig_file.write(signature)
        sig_file.flush()
        result = subprocess.run(["/usr/bin/ssh-keygen", "-Y", "verify", "-f", ALLOWED_SIGNERS, "-I", principal(),
                                 "-n", MESSAGE_NAMESPACE, "-s", sig_file.name],
                                input=payload_text.encode("utf-8"), capture_output=True)
    return result.returncode == 0


def parse(body, now=None):
    """The signed quiz payload, or None."""
    now = time.time() if now is None else now
    try:
        envelope = json.loads(body)
        payload_text, signature = envelope["payload"], envelope["sig"]
    except (ValueError, KeyError, TypeError):
        return None
    if not verify(payload_text, signature):
        log("Ignored a quiz message that isn't signed by the lab key.")
        return None
    try:
        message = json.loads(payload_text)
        sent = float(message["sent"])
        str(message["id"])
    except (ValueError, KeyError, TypeError):
        return None
    if now - sent > MAX_SITTING_SECONDS or sent - now > MAX_CLOCK_AHEAD_SECONDS:
        return None
    return message


def valid_sitting(value):
    return isinstance(value, str) and bool(SITTING_RE.match(value))


def name_list(value):
    """A list of names (lower case), None for 'everyone', or False if invalid."""
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        return False
    return [v.strip().lower() for v in value]


# ---------------------------------------------------------------- state on disk

def sitting_dir(sitting):
    return os.path.join(STATE_DIR, "sittings", sitting)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, data, mode=0o600, owner=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.chmod(path + ".new", mode)
    if owner is not None:
        os.chown(path + ".new", owner, -1)
    os.replace(path + ".new", path)


def sittings():
    """{sitting: start record} for every sitting this laptop knows."""
    found = {}
    for path in glob.glob(os.path.join(STATE_DIR, "sittings", "*", "start.json")):
        record = read_json(path)
        if record:
            found[record["sitting"]] = record
    return found


def handed_in(sitting, user):
    return os.path.exists(os.path.join(sitting_dir(sitting), "handed", f"{user}.json"))


# ---------------------------------------------------------------- the quiz package

def download(url, sha256, key):
    """The decrypted package (student half), or raise."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("not an https link")
    request = urllib.request.Request(url, headers={"User-Agent": "lab-quiz/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_PACKAGE_BYTES + 1)
    if len(data) > MAX_PACKAGE_BYTES or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("package doesn't match")
    plain = AESGCM(base64.b64decode(key)).decrypt(data[:12], data[12:], b"lab-quiz-package")
    return json.loads(zlib.decompress(plain))


def version_for(sitting, account, count):
    """Must match tools/labquiz/quizlib.version_for (the laptop reports it anyway)."""
    digest = 0
    for char in f"{sitting}:{account}":
        digest = (digest * 131 + ord(char)) % 2**61
    return digest % count


def handle_start(message, now=None):
    start = message.get("quiz_start")
    if not isinstance(start, dict) or not valid_sitting(start.get("sitting")):
        log(f"Ignored quiz message {message.get('id')}: bad start.")
        return
    sitting = start["sitting"]
    accounts, laptops = name_list(start.get("to_accounts")), name_list(start.get("to_laptops"))
    if accounts is False or laptops is False:
        log(f"Ignored quiz {sitting}: bad target list.")
        return
    if laptops is not None and HOSTNAME.lower() not in laptops:
        return
    with LOCK:
        old = read_json(os.path.join(sitting_dir(sitting), "start.json"))
        if old and old.get("ended") and not old.get("except"):
            return                                          # already over here
        record = {"sitting": sitting, "title": str(start.get("title", "Quiz"))[:200], "sent": float(message["sent"]),
                  "accounts": accounts, "ended": False, "except": [],
                  "package": {key: str(start.get(key, "")) for key in ("url", "sha256", "key")}}
        if old:
            record["ended"], record["except"] = old.get("ended", False), old.get("except", [])
        write_json(os.path.join(sitting_dir(sitting), "start.json"), record)
    log(f"Quiz {sitting} started" + (f" for {', '.join(accounts)}" if accounts else "") + ".")
    ensure_package(record)


DOWNLOAD_TRIES = {}


def ensure_package(record):
    """True once the quiz is here; downloads it (retrying every 15 s) if not."""
    sitting = record["sitting"]
    path = os.path.join(sitting_dir(sitting), "package.json")
    if os.path.exists(path):
        return True
    if time.time() - DOWNLOAD_TRIES.get(sitting, 0) < 15:
        return False
    DOWNLOAD_TRIES[sitting] = time.time()
    try:
        package = record["package"]
        write_json(path, download(package["url"], package["sha256"], package["key"]))
        log(f"Quiz {sitting}: quiz downloaded.")
        return True
    except Exception as error:
        log(f"Quiz {sitting}: couldn't get the quiz yet ({error.__class__.__name__}: {error}).")
        return False


def handle_end(message):
    end = message.get("quiz_end")
    if not isinstance(end, dict) or not valid_sitting(end.get("sitting")):
        return
    keep = name_list(end.get("except", [])) or []
    path = os.path.join(sitting_dir(end["sitting"]), "start.json")
    with LOCK:
        record = read_json(path)
        if not record:
            return
        record["ended"], record["except"] = True, keep
        write_json(path, record)
    log(f"Quiz {end['sitting']} ended" + (f" (still going: {', '.join(keep)})" if keep else "") + ".")


def handle_resend(message):
    resend = message.get("quiz_resend")
    if not isinstance(resend, dict) or not valid_sitting(resend.get("sitting")):
        return
    folder = os.path.join(sitting_dir(resend["sitting"]), "sent")
    with LOCK:
        for path in glob.glob(os.path.join(folder, "*")):
            os.unlink(path)
    log(f"Quiz {resend['sitting']}: hand-ins will be sent again.")


def handle(message):
    if "quiz_start" in message:
        handle_start(message)
    elif "quiz_end" in message:
        handle_end(message)
    elif "quiz_resend" in message:
        handle_resend(message)


# ---------------------------------------------------------------- sessions and windows

def logged_in_users():
    result = subprocess.run([LOGINCTL, "list-sessions", "--no-legend"], capture_output=True, text=True)
    return sorted({parts[2] for parts in (line.split() for line in result.stdout.splitlines())
                   if len(parts) > 5 and parts[5] == "user"})


def is_admin(user):
    try:
        entry = pwd.getpwnam(user)
        sudo = grp.getgrnam("sudo")
    except KeyError:
        return False
    return user in sudo.gr_mem or entry.pw_gid == sudo.gr_gid


def takes_quiz(record, user):
    if record["accounts"] is not None:
        return user.lower() in record["accounts"]
    return not is_admin(user)


def still_going(record, user):
    """True while this student's quiz is open (not handed in, not ended for them)."""
    if handed_in(record["sitting"], user):
        return False
    if record.get("ended") and user.lower() not in (record.get("except") or []):
        return False
    return time.time() - record["sent"] < MAX_SITTING_SECONDS


def unit_name(sitting):
    return f"lab-quiz-window-{sitting}.service"


def user_systemctl(user, *args):
    return subprocess.run([SYSTEMCTL, "--user", f"--machine={user}@", *args], capture_output=True, text=True)


def window_running(user, sitting):
    return user_systemctl(user, "is-active", "--quiet", unit_name(sitting)).returncode == 0


def start_window(user, sitting):
    user_systemctl(user, "reset-failed", unit_name(sitting))
    result = subprocess.run([SYSTEMD_RUN, "--quiet", "--collect", f"--machine={user}@", "--user",
                             f"--unit={unit_name(sitting)}", "--slice=session.slice",
                             "/usr/bin/python3", WINDOW, sitting], capture_output=True, text=True)
    return result.returncode == 0


def prepare_user(record, user):
    """Write this student's own version (only theirs) and status files."""
    sitting = record["sitting"]
    folder = os.path.join(RUN_DIR, sitting)
    os.makedirs(folder, mode=0o755, exist_ok=True)
    os.chmod(folder, 0o755)
    entry = pwd.getpwnam(user)
    mine = os.path.join(folder, f"{user}.json")
    if not os.path.exists(mine):
        package = read_json(os.path.join(sitting_dir(sitting), "package.json"))
        number = version_for(sitting, user, len(package["versions"]))
        version = dict(package["versions"][number])
        write_json(mine, {"sitting": sitting, "title": package["title"], "total": package["total"],
                          "account": user, **version}, mode=0o400, owner=entry.pw_uid)
        if not os.path.exists(opened_path(sitting, user)):
            write_json(opened_path(sitting, user), {"version": number})
            queue(sitting, user, "opened", {"version": number})
    set_status(sitting, user, {"state": "open"})


def opened_path(sitting, user):
    return os.path.join(sitting_dir(sitting), "opened", f"{user}.json")


def opened_users(sitting):
    return sorted(os.path.basename(path)[:-5] for path in glob.glob(os.path.join(sitting_dir(sitting), "opened", "*.json")))


def set_status(sitting, user, status):
    path = os.path.join(RUN_DIR, sitting, f"{user}.status")
    if read_json(path) != status:
        write_json(path, status, mode=0o644)


# ---------------------------------------------------------------- handing in

def submit_dir():
    return os.path.join(RUN_DIR, "submit")


def prepare_submit_dir():
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    os.makedirs(submit_dir(), exist_ok=True)
    os.chmod(submit_dir(), 0o1733)


def read_owned(path, uid, limit):
    """Bytes of a regular file owned by uid (no symlinks), or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_size > limit:
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return handle.read(limit + 1)
    finally:
        os.close(fd)


def saved_answers(sitting, user):
    """(answers, time saved, name) as the window last saved them (empty if none)."""
    entry = pwd.getpwnam(user)
    path = os.path.join(entry.pw_dir, ".local", "state", "lab-quiz", f"{sitting}.json")
    for parent in (os.path.join(entry.pw_dir, ".local"), os.path.join(entry.pw_dir, ".local", "state"),
                   os.path.dirname(path)):
        if os.path.islink(parent):
            return {}, None, ""
    raw = read_owned(path, entry.pw_uid, MAX_SAVE_BYTES)
    try:
        saved = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        saved = {}
    answers = saved.get("answers") if isinstance(saved, dict) else None
    if not isinstance(answers, dict):
        return {}, None, ""
    clean = {str(k)[:20]: v[:20000] for k, v in answers.items() if isinstance(v, str)}
    name = saved.get("name") if isinstance(saved.get("name"), str) else ""
    return clean, saved.get("saved"), " ".join(name.split())[:100]


def hand_in(record, user, how):
    sitting = record["sitting"]
    answers, saved, name = saved_answers(sitting, user)
    opened = read_json(opened_path(sitting, user), {})
    hand = {"version": opened.get("version"), "name": name, "answers": answers, "saved": saved, "how": how,
            "handed": int(time.time())}
    write_json(os.path.join(sitting_dir(sitting), "handed", f"{user}.json"), hand)
    queue(sitting, user, "handed", hand)
    set_status(sitting, user, {"state": "handed" if how == "submitted" else "ended"})
    log(f"Quiz {sitting}: {user}'s answers handed in ({how}, {len(answers)} answers).")


def take_submissions():
    """Hand in for every student who pressed Hand in."""
    try:
        names = os.listdir(submit_dir())
    except OSError:
        return
    for name in names:
        path = os.path.join(submit_dir(), name)
        try:
            info = os.lstat(path)
            raw = read_owned(path, info.st_uid, 1024)
            os.unlink(path)
            user = pwd.getpwuid(info.st_uid).pw_name
            sitting = json.loads(raw.decode("utf-8"))["sitting"] if raw else None
        except (OSError, KeyError, ValueError, UnicodeDecodeError, AttributeError):
            continue
        record = sittings().get(sitting)
        if record and takes_quiz(record, user) and still_going(record, user):
            hand_in(record, user, "submitted")


# ---------------------------------------------------------------- sending to the teacher

def queue(sitting, user, kind, data):
    message = {"v": 1, "kind": kind, "sitting": sitting, "user": user, "laptop": HOSTNAME,
               "sent": int(time.time()), **data}
    write_json(os.path.join(sitting_dir(sitting), "outbox", f"{kind}-{user}.json"), message)


def sign(text):
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "message")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        subprocess.run(["/usr/bin/ssh-keygen", "-Y", "sign", "-q", "-f", LAPTOP_KEY, "-n", ANSWER_NAMESPACE, path],
                       check=True, capture_output=True)
        with open(path + ".sig", encoding="utf-8") as handle:
            return handle.read()


def encrypt(plaintext):
    with open(TEACHER_KEY, "rb") as handle:
        teacher = serialization.load_pem_public_key(handle.read())
    secret = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    data = AESGCM(secret).encrypt(nonce, zlib.compress(plaintext, 9), None)
    wrapped = teacher.encrypt(secret, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                   algorithm=hashes.SHA256(), label=None))
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")
    return json.dumps({"lab_quiz": 1, "key": b64(wrapped), "nonce": b64(nonce), "data": b64(data)})


def body_for(message):
    text = json.dumps(message, sort_keys=True)
    with open(LAPTOP_KEY + ".pub", encoding="utf-8") as handle:
        public = handle.read().strip()
    return encrypt(json.dumps({"message": text, "sig": sign(text), "pubkey": public}).encode("utf-8"))


def send_outbox(server, topic):
    for path in sorted(glob.glob(os.path.join(STATE_DIR, "sittings", "*", "outbox", "*.json"))):
        folder = os.path.dirname(os.path.dirname(path))
        sent_marker = os.path.join(folder, "sent", os.path.basename(path))
        if os.path.exists(sent_marker):
            continue
        message = read_json(path)
        if not message:
            continue
        try:
            request = urllib.request.Request(f"{server}/{topic}", data=body_for(message).encode("utf-8"),
                                             method="POST", headers={"User-Agent": "lab-quiz/1"})
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            write_json(sent_marker, {"at": int(time.time())})
            log(f"Quiz {message['sitting']}: sent '{message['kind']}' for {message['user']}.")
        except Exception as error:
            log(f"Quiz {message['sitting']}: not sent yet ({error.__class__.__name__}); will retry.")
            return


# ---------------------------------------------------------------- lockdown

def nft(script):
    return subprocess.run([NFT, "-f", "-"], input=script, capture_output=True, text=True)


def addresses(host):
    found4, found6 = set(), set()
    try:
        for family, _t, _p, _c, address in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP):
            (found4 if family == socket.AF_INET else found6).add(address[0])
    except OSError:
        pass
    return found4, found6


def firewall_on(server_host, known):
    """Create or refresh the table. `known` keeps the addresses seen so far, so
    a failed lookup never empties the allow list."""
    four, six = addresses(server_host)
    known["4"] |= four
    known["6"] |= six
    elements4 = ", ".join(sorted(known["4"]))
    elements6 = ", ".join(sorted(known["6"]))
    script = (
        "table inet labquiz {}\n"
        "delete table inet labquiz\n"
        "table inet labquiz {\n"
        "  set allowed4 { type ipv4_addr; " + (f"elements = {{ {elements4} }}; " if elements4 else "") + "}\n"
        "  set allowed6 { type ipv6_addr; " + (f"elements = {{ {elements6} }}; " if elements6 else "") + "}\n"
        "  chain output {\n"
        "    type filter hook output priority 0; policy accept;\n"
        "    oifname \"lo\" accept\n"
        "    udp dport { 53, 67, 68, 123 } accept\n"
        "    tcp dport 53 accept\n"
        "    meta l4proto { icmp, ipv6-icmp } accept\n"
        "    ip daddr @allowed4 accept\n"
        "    ip6 daddr @allowed6 accept\n"
        "    reject\n"
        "  }\n"
        "}\n")
    result = nft(script)
    if result.returncode != 0:
        log(f"Firewall: nft failed: {result.stderr.strip()[:300]}")
    return result.returncode == 0


def firewall_off():
    nft("table inet labquiz {}\ndelete table inet labquiz\n")


def usb_interfaces():
    for path in glob.glob(os.path.join(USB_DEVICES, "*")):
        try:
            with open(os.path.join(path, "bInterfaceClass")) as handle:
                if handle.read().strip().lower() in USB_BLOCKED_CLASSES:
                    yield path
        except OSError:
            continue


def write_sys(path, value):
    try:
        with open(path, "w") as handle:
            handle.write(value)
        return True
    except OSError:
        return False


def usb_block():
    os.makedirs(os.path.dirname(UDEV_RULE), exist_ok=True)
    rule = ('ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_interface", '
            'ATTR{bInterfaceClass}=="08|06", ATTR{authorized}="0"\n')
    if read_text(UDEV_RULE) != rule:
        with open(UDEV_RULE, "w") as handle:
            handle.write("# Lab quiz in progress (lab-quiz.service): USB storage blocked.\n" + rule)
        subprocess.run([UDEVADM, "control", "--reload"], capture_output=True)
    for path in usb_interfaces():
        write_sys(os.path.join(path, "authorized"), "0")


def usb_unblock():
    if os.path.exists(UDEV_RULE):
        os.unlink(UDEV_RULE)
        subprocess.run([UDEVADM, "control", "--reload"], capture_output=True)
    for path in usb_interfaces():
        write_sys(os.path.join(path, "authorized"), "1")


def read_text(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return None


def closable(name):
    """Launched apps, never session services or the quiz window."""
    if "lab-quiz" in name:
        return False
    return (name.startswith("app-") or name.startswith("dbus-")
            or (name.startswith("snap.") and name.endswith(".scope")))


def close_apps(user):
    """Kill every launched app of this user. Returns the names closed."""
    uid = pwd.getpwnam(user).pw_uid
    app_slice = os.path.join(CGROUP_ROOT, "user.slice", f"user-{uid}.slice", f"user@{uid}.service", "app.slice")
    closed = []
    try:
        names = os.listdir(app_slice)
    except OSError:
        return closed
    for name in names:
        unit = os.path.join(app_slice, name)
        if os.path.isdir(unit) and closable(name):
            if read_text(os.path.join(unit, "cgroup.procs")) and write_sys(os.path.join(unit, "cgroup.kill"), "1"):
                closed.append(name)
    return closed


def command_line(user, disabled):
    """Switch GNOME's Alt+F2 command box off (or back on) for this user."""
    subprocess.run([SYSTEMD_RUN, "--quiet", "--collect", "--wait", f"--machine={user}@", "--user",
                    "/usr/bin/gsettings", "set", "org.gnome.desktop.lockdown", "disable-command-line",
                    "true" if disabled else "false"], capture_output=True, text=True, timeout=20)


# ---------------------------------------------------------------- the main loop

class Laptop:
    def __init__(self, server):
        self.server_host = urllib.parse.urlsplit(server).hostname
        self.locked_users = set()
        self.known = {"4": set(), "6": set()}
        self.locked = False
        self.last_refresh = 0

    def tick(self):
        """One round: open quizzes, hand in at the end, lock or unlock."""
        take_submissions()
        users = logged_in_users()
        want_locked = set()
        with LOCK:
            records = sittings()
        for sitting, record in records.items():
            for user in users:
                if takes_quiz(record, user) and still_going(record, user) and ensure_package(record):
                    prepare_user(record, user)
                    want_locked.add(user)
                    if not window_running(user, sitting):
                        log(f"Quiz {sitting}: opening the quiz for {user}.")
                        start_window(user, sitting)
            # Ended: hand in for everyone who opened it here, logged in or not.
            for user in opened_users(sitting):
                if record.get("ended") and not handed_in(sitting, user) and not still_going(record, user):
                    hand_in(record, user, "ended by teacher")
        self.lock(want_locked)

    def lock(self, users):
        if users:
            if not self.locked or time.time() - self.last_refresh > 60:
                firewall_on(self.server_host, self.known)
                usb_block()
                self.last_refresh = time.time()
                if not self.locked:
                    log("Lockdown on.")
                self.locked = True
            for user in users - self.locked_users:
                command_line(user, True)
            for user in users:
                closed = close_apps(user)
                if closed:
                    log(f"Closed for {user}: {', '.join(closed)}")
        for user in self.locked_users - users:
            command_line(user, False)
        self.locked_users = set(users)
        if not users and self.locked:
            self.unlock()

    def unlock(self):
        firewall_off()
        usb_unblock()
        self.locked = False
        log("Lockdown off.")


def listen(server, topic, stop=None):
    """Stream quiz messages; on every (re)connect fetch the last hours too."""
    seen = set()
    delay = 5
    while stop is None or not stop.is_set():
        url = f"{server}/{urllib.parse.quote(topic)}/json?since={MAX_SITTING_SECONDS // 3600}h"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "lab-quiz/1"})
            with urllib.request.urlopen(request, timeout=READ_TIMEOUT_SECONDS) as stream:
                delay = 5
                for raw in stream:
                    event = json.loads(raw)
                    if event.get("event") != "message" or event.get("id") in seen:
                        continue
                    seen.add(event.get("id"))
                    message = parse(event.get("message", ""))
                    if message:
                        handle(message)
        except Exception as error:
            log(f"Quiz channel: not connected ({error.__class__.__name__}); retrying in {delay} s.")
        time.sleep(delay)
        delay = min(delay * 2, 60)


def forget_old():
    """Remove sittings older than a week (hand-ins were sent long ago)."""
    for path in glob.glob(os.path.join(STATE_DIR, "sittings", "*")):
        record = read_json(os.path.join(path, "start.json"))
        if record and time.time() - record["sent"] > 7 * 86400:
            shutil.rmtree(path, ignore_errors=True)
            shutil.rmtree(os.path.join(RUN_DIR, record["sitting"]), ignore_errors=True)


def main():
    server, topic, answer_topic = read_config()
    os.makedirs(os.path.join(STATE_DIR, "sittings"), mode=0o700, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    prepare_submit_dir()
    laptop = Laptop(server)
    laptop.unlock()                         # never keep a lockdown from before a crash or reboot
    threading.Thread(target=listen, args=(server, topic), daemon=True).start()
    rounds = 0
    while True:
        try:
            laptop.tick()
            send_outbox(server, answer_topic)
            if rounds % 1800 == 0:
                forget_old()
        except Exception as error:          # never let the agent die
            log(f"Quiz agent: {error.__class__.__name__}: {error}")
        rounds += 1
        time.sleep(2)


if __name__ == "__main__":
    main()
