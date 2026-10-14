"""Old-style student accounts and their removal (lab update 0004).

Old-style = made with the old free-form "Create Student Account" panel, i.e.
a normal login account that is NOT:
  * a TDSB account ("tdsb-" + ID, from the TDSB login: students and staff),
  * listed in /etc/school-account/keep-accounts (administrator, test accounts),
  * a system account (UID below 1000 or 60000 and up).

When update 0004 first runs on a laptop it writes the old-style accounts that
exist at that moment to /var/lib/school-account/legacy-to-remove ("name:uid"
per line). Only accounts on that list are ever deleted, and only if the UID
still matches, so accounts created later are never affected.
"""

import os
import pwd
import re

KEEP_FILE = os.environ.get("SCHOOL_KEEP_ACCOUNTS", "/etc/school-account/keep-accounts")
REMOVE_LIST = os.environ.get("SCHOOL_LEGACY_LIST", "/var/lib/school-account/legacy-to-remove")

TDSB_ACCOUNT_PATTERN = re.compile(r"^tdsb-[a-z0-9]{3,27}$")
NORMAL_SHELLS = {"/bin/bash", "/usr/bin/bash"}


def keep_list():
    try:
        with open(KEEP_FILE, "r", encoding="utf-8") as keep_file:
            names = {
                line.strip()
                for line in keep_file
                if line.strip() and not line.strip().startswith("#")
            }
    except FileNotFoundError:
        names = set()

    # Never rely on the file alone for these.
    return names | {"root", "administrator"}


def is_legacy(account, keep=None):
    keep = keep_list() if keep is None else keep

    if account.pw_name in keep:
        return False

    if TDSB_ACCOUNT_PATTERN.fullmatch(account.pw_name):
        return False

    if not 1000 <= account.pw_uid < 60000:
        return False

    if account.pw_dir != f"/home/{account.pw_name}":
        return False

    return account.pw_shell in NORMAL_SHELLS


def legacy_accounts(all_accounts=None):
    keep = keep_list()
    accounts = pwd.getpwall() if all_accounts is None else all_accounts
    return sorted(
        (account for account in accounts if is_legacy(account, keep)),
        key=lambda account: account.pw_name,
    )


def read_remove_list():
    """[(name, uid), ...] still to remove; [] if none or no list."""
    entries = []

    try:
        with open(REMOVE_LIST, "r", encoding="utf-8") as remove_list:
            for line in remove_list:
                name, separator, uid = line.strip().partition(":")
                if separator and name and uid.isdigit():
                    entries.append((name, int(uid)))
    except FileNotFoundError:
        pass

    return entries


def write_remove_list(entries):
    temp_path = REMOVE_LIST + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as remove_list:
        for name, uid in entries:
            remove_list.write(f"{name}:{uid}\n")
        remove_list.flush()
        os.fsync(remove_list.fileno())

    os.chmod(temp_path, 0o600)
    os.replace(temp_path, REMOVE_LIST)


def snapshot_remove_list():
    """Record today's old-style accounts (only if no list exists yet)."""
    if os.path.exists(REMOVE_LIST):
        return read_remove_list()

    entries = [(account.pw_name, account.pw_uid) for account in legacy_accounts()]
    write_remove_list(entries)
    return entries
