#!/usr/bin/env python3
"""Fix the Java version in new IntelliJ JavaFX projects (lab update 0013).

IntelliJ's New Project > JavaFX wizard writes Java 8 into pom.xml
(<source>8</source> <target>8</target>), so the project fails with
"modules are not supported in -source 8". This runs in each person's desktop
session (systemd user service), looks for such pom.xml files in their home
folder every few seconds, and changes them to <release>25</release> (or the
project's JDK, if .idea/misc.xml names one). IntelliJ then reloads the project.

Only JavaFX Maven projects (an org.openjfx dependency or a module-info.java)
are touched, and each file only once, so a later manual change is respected.
"""

import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.environ.get("LAB_JAVAFX_STATE", os.path.join(HOME, ".local", "state", "lab-javafx"))
FIXED_LIST = os.path.join(STATE_DIR, "fixed")
LOG_FILE = os.path.join(STATE_DIR, "fixer.log")

DEFAULT_RELEASE = "25"
MAX_DEPTH = 4
SKIP_DIRS = {"target", "node_modules", "snap", "build", "out"}
POLL_SECONDS = 3

COMPILER_PLUGIN = re.compile(
    r"<artifactId>\s*maven-compiler-plugin\s*</artifactId>.*?</plugin>", re.S)
OLD_SOURCE = re.compile(r"^([ \t]*)<source>\s*(?:1\.)?8\s*</source>[ \t]*$", re.M)
OLD_TARGET = re.compile(r"^[ \t]*<target>\s*(?:1\.)?8\s*</target>[ \t]*\n?", re.M)
OLD_PROP_SOURCE = re.compile(
    r"^([ \t]*)<maven\.compiler\.source>\s*(?:1\.)?8\s*</maven\.compiler\.source>[ \t]*$", re.M)
OLD_PROP_TARGET = re.compile(
    r"^[ \t]*<maven\.compiler\.target>\s*(?:1\.)?8\s*</maven\.compiler\.target>[ \t]*\n?", re.M)
JDK_NAME = re.compile(r'project-jdk-name="(\d{2})"')


def log(message):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")


def find_poms(root=None, depth=0):
    root = HOME if root is None else root
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        if entry.name == "pom.xml" and entry.is_file(follow_symlinks=False):
            yield entry.path
        elif (depth < MAX_DEPTH and entry.is_dir(follow_symlinks=False)
              and not entry.name.startswith(".") and entry.name not in SKIP_DIRS):
            yield from find_poms(entry.path, depth + 1)


def is_javafx_project(project_dir, text):
    return ("org.openjfx" in text
            or os.path.exists(os.path.join(project_dir, "src", "main", "java", "module-info.java")))


def release_for(project_dir):
    try:
        with open(os.path.join(project_dir, ".idea", "misc.xml"), "r", encoding="utf-8") as misc:
            match = JDK_NAME.search(misc.read())
    except OSError:
        match = None
    if match and int(match.group(1)) >= 11:
        return match.group(1)
    return DEFAULT_RELEASE


def fixed_text(text, release):
    """The corrected pom.xml text, or None if it doesn't need fixing."""
    new_text = text
    block = COMPILER_PLUGIN.search(new_text)

    if block and OLD_SOURCE.search(block.group(0)):
        fixed_block = OLD_SOURCE.sub(lambda m: f"{m.group(1)}<release>{release}</release>", block.group(0), count=1)
        fixed_block = OLD_TARGET.sub("", fixed_block, count=1)
        new_text = new_text[:block.start()] + fixed_block + new_text[block.end():]

    if OLD_PROP_SOURCE.search(new_text):
        new_text = OLD_PROP_SOURCE.sub(
            lambda m: f"{m.group(1)}<maven.compiler.release>{release}</maven.compiler.release>", new_text, count=1)
        new_text = OLD_PROP_TARGET.sub("", new_text, count=1)

    return None if new_text == text else new_text


def read_fixed():
    try:
        with open(FIXED_LIST, "r", encoding="utf-8") as fixed:
            return {line.rstrip("\n") for line in fixed if line.strip()}
    except OSError:
        return set()


def remember_fixed(path):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FIXED_LIST, "a", encoding="utf-8") as fixed:
        fixed.write(path + "\n")


def notify(project, release):
    subprocess.run(
        ["notify-send", "--app-name=Lab", "JavaFX project fixed",
         f"\"{project}\" now uses Java {release}. If IntelliJ asks, click \"Load Maven Changes\"."],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


def fix_pom(path, fixed):
    """Fix one pom.xml if needed. Returns True if it was changed."""
    if path in fixed:
        return False
    try:
        with open(path, "r", encoding="utf-8") as pom:
            text = pom.read()
    except (OSError, UnicodeDecodeError):
        return False

    project_dir = os.path.dirname(path)
    if not is_javafx_project(project_dir, text):
        return False

    release = release_for(project_dir)
    new_text = fixed_text(text, release)
    if new_text is None:
        return False

    temp_path = path + ".lab-fix.tmp"
    with open(temp_path, "w", encoding="utf-8") as temp:
        temp.write(new_text)
    os.chmod(temp_path, os.stat(path).st_mode & 0o7777)
    os.replace(temp_path, path)

    fixed.add(path)
    remember_fixed(path)
    log(f"fixed {path}: Java 8 -> {release}")
    notify(os.path.basename(project_dir), release)
    return True


def scan_once(fixed, seen):
    for path in find_poms():
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if seen.get(path) == mtime:
            continue
        seen[path] = mtime
        if fix_pom(path, fixed):
            seen[path] = os.stat(path).st_mtime


def main():
    fixed = read_fixed()
    seen = {}
    while True:
        try:
            scan_once(fixed, seen)
        except Exception as error:  # never die on one bad file
            log(f"error: {error!r}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
