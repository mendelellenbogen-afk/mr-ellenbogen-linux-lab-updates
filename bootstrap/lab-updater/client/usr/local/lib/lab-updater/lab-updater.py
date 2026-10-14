#!/usr/bin/env python3
"""Lab updater: pull signed updates from GitHub and apply each one once, in order.

Each update is a folder  updates/NNNN-short-name/  containing an executable
install.sh. The updater:

  1. fetches the configured branch of the update repo,
  2. refuses to continue unless the branch tip is a commit signed by a key in
     allowed_signers, and is the same as or newer than the last trusted commit
     (no rollbacks),
  3. runs every update not yet recorded as applied, in number order, as root,
  4. stops at the first failure (later updates may depend on earlier ones);
     the failed update is retried on the next run,
  5. writes a world-readable status.json describing the result.

Settings come from /etc/lab-updater/config (KEY=VALUE lines). Every path can be
overridden with environment variables, which the test suite uses.
"""

import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys

CONFIG_FILE = os.environ.get("LAB_UPDATER_CONFIG", "/etc/lab-updater/config")
ALLOWED_SIGNERS = os.environ.get(
    "LAB_UPDATER_ALLOWED_SIGNERS", "/etc/lab-updater/allowed_signers"
)
STATE_DIR = os.environ.get("LAB_UPDATER_STATE_DIR", "/var/lib/lab-updater")
STATUS_FILE = os.environ.get(
    "LAB_UPDATER_STATUS_FILE", "/var/lib/lab-updater/status.json"
)
LOG_DIR = os.environ.get("LAB_UPDATER_LOG_DIR", "/var/log/lab-updater")
HELPERS_FILE = os.environ.get(
    "LAB_UPDATER_HELPERS", "/usr/local/lib/lab-updater/update-helpers.sh"
)

REPO_DIR = os.path.join(STATE_DIR, "repo")
APPLIED_DIR = os.path.join(STATE_DIR, "applied")
TRUSTED_COMMIT_FILE = os.path.join(STATE_DIR, "last-trusted-commit")
LOCK_FILE = os.path.join(STATE_DIR, "lock")

UPDATE_NAME_PATTERN = re.compile(r"^[0-9]{4}-[a-z0-9][a-z0-9-]{0,60}$")
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
UPDATE_TIMEOUT_SECONDS = 60 * 60
GIT_TIMEOUT_SECONDS = 10 * 60


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def log(message):
    print(message, flush=True)


def read_config():
    config = {}

    with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
        for line in config_file:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            key, separator, value = line.partition("=")

            if separator:
                config[key.strip()] = value.strip()

    repo_url = config.get("REPO_URL", "")
    branch = config.get("BRANCH", "")

    if not repo_url:
        raise ValueError("REPO_URL is missing from the config file.")

    if not BRANCH_PATTERN.fullmatch(branch) or ".." in branch:
        raise ValueError("BRANCH is missing or invalid in the config file.")

    return repo_url, branch


def git(*args, check=True):
    return subprocess.run(
        ["git", "-C", REPO_DIR, *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def prepare_repo(repo_url):
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        if os.path.exists(REPO_DIR):
            shutil.rmtree(REPO_DIR)

        os.makedirs(REPO_DIR, mode=0o700)
        git("init", "--quiet")
        git("remote", "add", "origin", repo_url)
    else:
        git("remote", "set-url", "origin", repo_url)

    # Signature checking uses SSH keys listed in allowed_signers.
    git("config", "gpg.format", "ssh")
    git("config", "gpg.ssh.allowedSignersFile", ALLOWED_SIGNERS)


def fetch(branch):
    # A full fetch keeps history, which the rollback check needs.
    git(
        "fetch",
        "--quiet",
        "--prune",
        "origin",
        f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
    )

    return git("rev-parse", f"refs/remotes/origin/{branch}").stdout.strip()


def verify_commit(commit):
    result = git("verify-commit", commit, check=False)

    if result.returncode != 0:
        raise PermissionError(
            f"Commit {commit[:12]} is not signed by a trusted key: "
            f"{result.stderr.strip()}"
        )


def check_not_rollback(commit):
    try:
        with open(TRUSTED_COMMIT_FILE, "r", encoding="utf-8") as trusted_file:
            last_trusted = trusted_file.read().strip()
    except FileNotFoundError:
        return

    if not last_trusted or last_trusted == commit:
        return

    result = git("merge-base", "--is-ancestor", last_trusted, commit, check=False)

    if result.returncode != 0:
        raise PermissionError(
            f"Commit {commit[:12]} does not build on the last trusted commit "
            f"{last_trusted[:12]}. Refusing a possible rollback."
        )


def write_file_atomically(path, contents, mode=0o600):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as temp_file:
        temp_file.write(contents)
        temp_file.flush()
        os.fsync(temp_file.fileno())

    os.chmod(temp_path, mode)
    os.replace(temp_path, path)


def checkout(commit):
    git("checkout", "--quiet", "--force", "--detach", commit)
    git("clean", "--quiet", "-d", "--force", "-x")
    write_file_atomically(TRUSTED_COMMIT_FILE, commit + "\n")


def pending_updates():
    updates_dir = os.path.join(REPO_DIR, "updates")

    if not os.path.isdir(updates_dir):
        return []

    names = sorted(
        name
        for name in os.listdir(updates_dir)
        if UPDATE_NAME_PATTERN.fullmatch(name)
        and os.path.isdir(os.path.join(updates_dir, name))
    )

    return [
        name
        for name in names
        if not os.path.exists(os.path.join(APPLIED_DIR, name))
    ]


def repair_interrupted_package_install():
    """If an earlier apt/dpkg run was cut off (e.g. Wi-Fi dropped at logout), finish it."""
    pending = "/var/lib/dpkg/updates"

    if os.geteuid() != 0 or not os.path.isdir(pending) or not os.listdir(pending):
        return

    log("Repairing an interrupted package installation (dpkg --configure -a).")
    subprocess.run(
        ["dpkg", "--configure", "-a"],
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        check=False,
    )


def run_update(name, commit):
    update_dir = os.path.join(REPO_DIR, "updates", name)
    script = os.path.join(update_dir, "install.sh")

    if not os.path.isfile(script):
        return False, "install.sh is missing"

    log_path = os.path.join(LOG_DIR, f"{name}.log")
    environment = {
        **os.environ,
        "DEBIAN_FRONTEND": "noninteractive",
        "LAB_UPDATE_NAME": name,
        "LAB_UPDATE_DIR": update_dir,
        "LAB_UPDATER_HELPERS": HELPERS_FILE,
    }

    log(f"Applying update {name}.")

    with open(log_path, "a", encoding="utf-8") as update_log:
        update_log.write(f"===== {now()} applying {name} at commit {commit}\n")
        update_log.flush()

        try:
            result = subprocess.run(
                ["/bin/bash", script],
                cwd=update_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=update_log,
                stderr=subprocess.STDOUT,
                timeout=UPDATE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            update_log.write(f"===== {now()} TIMED OUT\n")
            return False, "timed out"

        update_log.write(f"===== {now()} exit status {result.returncode}\n")

    if result.returncode != 0:
        return False, f"install.sh exited with status {result.returncode} (see {log_path})"

    write_file_atomically(
        os.path.join(APPLIED_DIR, name),
        f"APPLIED_AT={now()}\nCOMMIT={commit}\n",
        mode=0o644,
    )
    log(f"Update {name} applied.")

    return True, "OK"


def read_hardware_serial():
    try:
        with open("/sys/class/dmi/id/product_serial", "r", encoding="utf-8") as serial:
            return serial.read().strip()
    except OSError:
        return ""


def write_status(status):
    status["finished_at"] = now()
    status["hostname"] = os.uname().nodename
    status["hardware_serial"] = read_hardware_serial()

    try:
        status["applied"] = sorted(os.listdir(APPLIED_DIR))
    except OSError:
        status["applied"] = []

    write_file_atomically(STATUS_FILE, json.dumps(status, indent=2) + "\n", mode=0o644)


def main():
    for directory in (STATE_DIR, APPLIED_DIR, LOG_DIR):
        os.makedirs(directory, mode=0o755, exist_ok=True)

    lock = open(LOCK_FILE, "w")

    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Another update run is already in progress.")
        return 0

    status = {
        "started_at": now(),
        "result": "error",
        "message": "",
        "commit": "",
        "installed_this_run": [],
        "failed_update": "",
    }

    try:
        repo_url, branch = read_config()
        status["branch"] = branch

        prepare_repo(repo_url)

        try:
            commit = fetch(branch)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            status["result"] = "offline"
            status["message"] = "Could not reach the update server."
            log(f"Fetch failed: {getattr(error, 'stderr', '') or error}")
            return 0

        verify_commit(commit)
        check_not_rollback(commit)
        checkout(commit)
        status["commit"] = commit

        repair_interrupted_package_install()

        for name in pending_updates():
            success, message = run_update(name, commit)

            if not success:
                status["result"] = "failed"
                status["failed_update"] = name
                status["message"] = f"Update {name} failed: {message}"
                log(status["message"])
                return 1

            status["installed_this_run"].append(name)

        status["result"] = "ok"

        if status["installed_this_run"]:
            status["message"] = (
                f"Installed {len(status['installed_this_run'])} update(s)."
            )
        else:
            status["message"] = "Up to date."

        log(status["message"])
        return 0

    except PermissionError as error:
        status["result"] = "rejected"
        status["message"] = str(error)
        log(f"SECURITY: {error}")
        return 1

    except Exception as error:
        status["message"] = f"Unexpected error: {error}"
        log(status["message"])
        return 1

    finally:
        write_status(status)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
