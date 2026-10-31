"""Clear every student account from the login screen (lab updates 0050, 0053).

The teacher's request (2026-10-27): a button on the login screen that, after
the administrator password, deletes every account on the laptop except
administrator, StudentTest1 and StudentTest2. Logged-in students are logged
out first (unsaved work is lost: the teacher's choice).

An account is cleared when it is a normal login account:
  * UID 1000-59999 (not a system account),
  * a real login shell (not nologin/false),
  * not root, administrator, studenttest1 or studenttest2,
  * not an admin account (in the sudo group; update 0053, the teacher's
    request 2026-10-30: a colleague's admin account must survive the button).
Its home must be /home/<name>; any other home is left alone and reported as
"skipped", so userdel --remove can never touch a folder outside /home.

Quiz hand-ins wait in /var/lib/lab-quiz (not in the student's home), so
clearing accounts doesn't lose them.
"""

import ctypes
import ctypes.util
import grp
import hmac
import os
import pwd
import subprocess
import time

ADMIN = "administrator"
KEEP = {"root", ADMIN, "studenttest1", "studenttest2"}
NO_LOGIN_SHELLS = {"", "/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false"}

SHADOW = os.environ.get("SCHOOL_SHADOW", "/etc/shadow")
# Delete My Account requests and AccountsService's saved settings for an
# account: left behind they would refer to an account that is gone.
MARKER_DIRS = (
    "/run/school-account-self-delete",
    "/var/lib/school-account/self-delete-scheduled",
    "/var/lib/AccountsService/users",
    "/var/lib/AccountsService/icons",
)

LOGOUT_WAIT = 10      # seconds for a session to close after terminate-user
KILL_WAIT = 5         # seconds after pkill -KILL

_libcrypt = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1")
_libcrypt.crypt.restype = ctypes.c_char_p
_libcrypt.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]


def admin_hash():
    """The administrator's password hash from /etc/shadow, or None."""
    try:
        with open(SHADOW, "r", encoding="utf-8") as shadow:
            for line in shadow:
                fields = line.rstrip("\n").split(":")
                if len(fields) > 1 and fields[0] == ADMIN:
                    return fields[1]
    except OSError:
        return None
    return None


def check_admin_password(password):
    stored = admin_hash()
    # "!" or "*" = locked or no password: never accept anything.
    if not stored or stored[0] in "!*" or not password:
        return False
    result = _libcrypt.crypt(password.encode("utf-8"), stored.encode("utf-8"))
    return bool(result) and hmac.compare_digest(result, stored.encode("utf-8"))


def admin_names():
    """(member names, group id) of the sudo group; (set(), None) if there is none."""
    try:
        group = grp.getgrnam("sudo")
    except KeyError:
        return set(), None
    return set(group.gr_mem), group.gr_gid


def accounts_to_clear(all_accounts=None, admins=None):
    """(to_delete, skipped): accounts sorted by name."""
    accounts = pwd.getpwall() if all_accounts is None else all_accounts
    admin_members, admin_gid = admin_names() if admins is None else admins
    to_delete, skipped = [], []

    for account in sorted(accounts, key=lambda a: a.pw_name):
        if account.pw_name in KEEP:
            continue
        if account.pw_name in admin_members or account.pw_gid == admin_gid:
            continue
        if not 1000 <= account.pw_uid < 60000:
            continue
        if account.pw_shell in NO_LOGIN_SHELLS:
            continue
        if account.pw_dir != f"/home/{account.pw_name}":
            skipped.append(account)
            continue
        to_delete.append(account)

    return to_delete, skipped


def has_processes(uid):
    result = subprocess.run(["/usr/bin/pgrep", "-u", str(uid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def wait_until_gone(uid, seconds):
    deadline = time.monotonic() + seconds
    while has_processes(uid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)
    return True


def log_out(account, log):
    """Close every session and process of the account. True when none are left."""
    if not has_processes(account.pw_uid):
        return True

    log(f"Logging out '{account.pw_name}'.")
    subprocess.run(["/usr/bin/loginctl", "terminate-user", str(account.pw_uid)],
                   capture_output=True, check=False)
    if wait_until_gone(account.pw_uid, LOGOUT_WAIT):
        return True

    subprocess.run(["/usr/bin/pkill", "-KILL", "-u", str(account.pw_uid)],
                   capture_output=True, check=False)
    return wait_until_gone(account.pw_uid, KILL_WAIT)


def remove_markers(name):
    for directory in MARKER_DIRS:
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            pass


def delete_account(account, log):
    name = account.pw_name

    if not log_out(account, log):
        log(f"ERROR: '{name}' still has processes running; not deleted.")
        return False

    result = subprocess.run(["/usr/sbin/userdel", "--remove", name],
                            capture_output=True, text=True, check=False)
    # 12 = the account is gone but its home or mail spool wasn't fully removed.
    if result.returncode not in (0, 12):
        log(f"ERROR: could not delete '{name}': {result.stderr.strip() or result.returncode}")
        return False
    if result.returncode == 12:
        log(f"WARNING: '{name}' deleted, but its home folder was not fully removed.")

    remove_markers(name)
    log(f"Deleted '{name}' and its home folder.")
    return True


def clear_all(log=print):
    """Delete every account accounts_to_clear() picks. Returns a message."""
    to_delete, skipped = accounts_to_clear()
    failed = [account.pw_name for account in to_delete if not delete_account(account, log)]
    deleted = len(to_delete) - len(failed)

    message = f"Deleted {deleted} account{'s' if deleted != 1 else ''}."
    if failed:
        message += f" Could not delete {len(failed)} (see the laptop's journal)."
    if skipped:
        message += f" Left {len(skipped)} with an unusual home folder alone."
    return message
