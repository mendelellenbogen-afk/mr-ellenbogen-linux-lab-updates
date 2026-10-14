#!/usr/bin/env python3
# Deletes the old-style accounts recorded by lab update 0004 (see
# legacy_accounts.py). Runs once when 0004 installs, at boot, and hourly.
#
# For each listed account:
#   * gone, or its UID changed (a different account now)  -> drop from the list
#   * logged in / programs running -> hand it to the self-delete worker with a
#     "delete now" request, which removes it seconds after the person logs out
#     (requests in /run vanish at reboot; this script re-creates them)
#   * otherwise -> delete it and its home folder now

import os
import pwd
import subprocess
import sys

sys.path.insert(0, "/usr/local/lib/school-account")
import legacy_accounts  # noqa: E402

SELF_DELETE_PENDING = os.environ.get("SCHOOL_SELF_DELETE_PENDING", "/run/school-account-self-delete")


def busy_reason(uid):
    sessions = subprocess.run(
        ["/usr/bin/loginctl", "list-sessions", "--no-legend"],
        capture_output=True, text=True, check=False,
    )

    if sessions.returncode != 0:
        return "could not check sessions"

    for line in sessions.stdout.splitlines():
        parts = line.split()

        if len(parts) > 1 and parts[1] == str(uid):
            return "logged in"

    processes = subprocess.run(
        ["/usr/bin/pgrep", "-u", str(uid)],
        capture_output=True, text=True, check=False,
    )

    if processes.returncode == 0:
        return "programs still running"

    if processes.returncode != 1:
        return "could not check running programs"

    return None


def request_delete_after_logout(name, uid):
    """Same request format the Delete My Account "Delete now" path uses."""
    os.makedirs(SELF_DELETE_PENDING, mode=0o700, exist_ok=True)
    path = os.path.join(SELF_DELETE_PENDING, name)

    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return

    with os.fdopen(fd, "w") as marker:
        marker.write(f"UID={uid}\nUSERNAME={name}\n")

    if os.geteuid() == 0:
        os.chown(path, 0, 0)
    os.chmod(path, 0o600)


def main():
    remaining = []
    failures = 0

    for name, uid in legacy_accounts.read_remove_list():
        try:
            account = pwd.getpwnam(name)
        except KeyError:
            print(f"'{name}' is already gone.")
            continue

        if account.pw_uid != uid or not legacy_accounts.is_legacy(account):
            print(f"'{name}' is not the account that was listed; leaving it alone.")
            continue

        reason = busy_reason(uid)

        if reason:
            request_delete_after_logout(name, uid)
            print(f"'{name}': {reason}; will be deleted right after logout.")
            remaining.append((name, uid))
            continue

        result = subprocess.run(
            ["/usr/sbin/userdel", "--remove", name],
            capture_output=True, text=True, check=False,
        )

        if result.returncode == 0:
            print(f"Removed old account '{name}' and its home folder.")
        else:
            failures += 1
            remaining.append((name, uid))
            print(f"ERROR removing '{name}': {result.stderr.strip()}")

    legacy_accounts.write_remove_list(remaining)

    if not remaining:
        print("No old accounts left to remove.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
