#!/usr/bin/env python3

import datetime
import os
import pwd
import grp
import time
import subprocess

# "Delete now": removed right after logout. Lives in /run (cleared at reboot).
PENDING_DIR = "/run/school-account-self-delete"

# "Delete in 7 days": removed once the date has passed and the user is not
# logged in. Lives in /var/lib so it survives reboots.
SCHEDULED_DIR = "/var/lib/school-account/self-delete-scheduled"
SCHEDULED_CHECK_EVERY = 60    # loop rounds of 5 s = every 5 minutes

NOW_FIELDS = {"UID", "USERNAME"}
SCHEDULED_FIELDS = {"UID", "USERNAME", "DELETE_AFTER"}

PROTECTED_USERS = {
    "root",
    "administrator",
    "teststudent",
    "studenttwo",
    "studenttest1",
    "studenttest2",
}


def get_sessions(uid):
    result = subprocess.run(
        [
            "/usr/bin/loginctl",
            "list-sessions",
            "--no-legend",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return None

    sessions = []

    for line in result.stdout.splitlines():
        parts = line.split()

        if len(parts) < 2:
            continue

        session_id = parts[0]

        try:
            session_uid = int(parts[1])
        except ValueError:
            continue

        if session_uid == uid:
            sessions.append(session_id)

    return sessions


def validate_account(username, expected_uid):
    if username in PROTECTED_USERS:
        return False, "protected account"

    try:
        account = pwd.getpwnam(username)
    except KeyError:
        return False, "account does not exist"

    if account.pw_uid != expected_uid:
        return False, "UID does not match the pending request"

    if account.pw_uid < 1000:
        return False, "UID is below 1000"

    if account.pw_dir != f"/home/{username}":
        return False, "home directory is not /home/username"

    if account.pw_shell != "/bin/bash":
        return False, "shell is not /bin/bash"

    try:
        primary_group = grp.getgrgid(account.pw_gid)
    except KeyError:
        return False, "primary group does not exist"

    if primary_group.gr_name != username:
        return False, "primary group does not match username"

    return True, "OK"



def get_user_processes(uid):
    result = subprocess.run(
        [
            "/usr/bin/pgrep",
            "-u",
            str(uid),
            "-a",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 1:
        return []

    if result.returncode != 0:
        return None

    processes = []

    for line in result.stdout.splitlines():
        line = line.strip()

        if line:
            processes.append(line)

    return processes


def read_marker(path, required=NOW_FIELDS):
    try:
        stat = os.stat(path)

        if stat.st_uid != 0:
            return None, "marker is not owned by root"

        if stat.st_mode & 0o777 != 0o600:
            return None, "marker permissions are not 600"

        with open(path, "r", encoding="utf-8") as marker:
            lines = marker.read().splitlines()

    except OSError as error:
        return None, f"could not read marker: {error}"

    values = {}

    for line in lines:
        if "=" not in line:
            return None, "invalid marker format"

        key, value = line.split("=", 1)

        if key not in required:
            return None, "unexpected marker field"

        if key in values:
            return None, "duplicate marker field"

        values[key] = value

    if set(values.keys()) != required:
        return None, "marker is missing required fields"

    try:
        uid = int(values["UID"])
    except ValueError:
        return None, "marker UID is not numeric"

    username = values["USERNAME"]

    if not username:
        return None, "marker username is empty"

    if uid < 1000:
        return None, "marker UID is below 1000"

    marker = {
        "uid": uid,
        "username": username,
    }

    if "DELETE_AFTER" in required:
        try:
            marker["delete_after"] = datetime.date.fromisoformat(values["DELETE_AFTER"])
        except ValueError:
            return None, "marker DELETE_AFTER is not a date"

    return marker, "OK"


def process_request(path, scheduled=False):
    filename = os.path.basename(path)

    marker, reason = read_marker(path, SCHEDULED_FIELDS if scheduled else NOW_FIELDS)

    if marker is None:
        print(
            f"Pending deletion '{filename}' rejected: {reason}."
        )
        return

    username = marker["username"]
    uid = marker["uid"]

    if username != filename:
        print(
            f"Pending deletion '{filename}' rejected: "
            f"marker username does not match filename."
        )
        return

    if scheduled:
        if datetime.date.today() < marker["delete_after"]:
            return

        try:
            current_uid = pwd.getpwnam(username).pw_uid
        except KeyError:
            current_uid = None

        if current_uid != uid:
            # Already gone (e.g. "Delete now" was chosen later), or this is a
            # NEW account with the same name: the old request no longer applies.
            os.unlink(path)
            print(f"Scheduled deletion '{username}' discarded: the account it was for no longer exists.")
            return

    valid, reason = validate_account(username, uid)

    if not valid:
        print(
            f"Pending deletion '{username}' rejected: {reason}."
        )
        return

    sessions = get_sessions(uid)

    if sessions is None:
        print(
            f"Pending deletion '{username}': "
            f"could not safely determine active sessions."
        )
        return

    if sessions:
        print(
            f"Pending deletion '{username}': "
            f"still has active sessions: {', '.join(sessions)}"
        )
        return

    processes = get_user_processes(uid)

    if processes is None:
        print(
            f"Pending deletion '{username}': "
            f"could not safely determine remaining processes."
        )
        return

    if processes:
        print(
            f"Pending deletion '{username}': "
            f"still has processes running: {' | '.join(processes)}"
        )
        return

    print(
        f"Deleting account '{username}': all safety checks passed."
    )

    result = subprocess.run(
        [
            "/usr/sbin/userdel",
            "--remove",
            username,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        error = result.stderr.strip()

        if not error:
            error = "userdel returned a non-zero exit status."

        print(
            f"ERROR: Could not delete account '{username}': {error}"
        )
        return

    try:
        os.unlink(path)
    except OSError as error:
        print(
            f"WARNING: Account '{username}' was deleted, "
            f"but the pending marker could not be removed: {error}"
        )
        return

    print(
        f"Account '{username}' was successfully deleted "
        f"and its home directory was removed."
    )


def process_scheduled():
    try:
        entries = os.listdir(SCHEDULED_DIR)
    except FileNotFoundError:
        return
    except OSError as error:
        print(f"ERROR: Cannot read scheduled directory: {error}")
        return

    for entry in entries:
        path = os.path.join(SCHEDULED_DIR, entry)

        if os.path.isfile(path):
            process_request(path, scheduled=True)


def main():
    os.makedirs(PENDING_DIR, mode=0o700, exist_ok=True)
    rounds = 0

    while True:
        if rounds % SCHEDULED_CHECK_EVERY == 0:
            process_scheduled()

        rounds += 1

        try:
            entries = os.listdir(PENDING_DIR)
        except OSError as error:
            print(f"ERROR: Cannot read pending directory: {error}")
            time.sleep(5)
            continue

        for entry in entries:
            path = os.path.join(PENDING_DIR, entry)

            if not os.path.isfile(path):
                continue

            process_request(path)

        time.sleep(5)


if __name__ == "__main__":
    main()
