#!/usr/bin/env python3
"""Save to GitHub (update 0026): students put their projects on GitHub with one button.

The teacher's choices (2026-10-18):
  * Students make their own free GitHub accounts and know nothing about GitHub,
    so everything is buttons: no terminal, no git words.
  * New projects are private on GitHub.
  * Students use mixed laptops, so "Get a project from GitHub" downloads a
    project onto this laptop; GitHub Classroom repos (in an organisation) are
    listed too.

How it works:
  * Sign in: `gh auth login --web` prints a one-time code; the window shows it
    big with a "Copy the code and open GitHub" button. The token is kept in
    ~/.config/gh/hosts.yml (the home folder is private), not in the keyring:
    TDSB passwords change, and a keyring that no longer unlocks would ask
    students for an old password. `gh auth setup-git` then lets git (and VS
    Code, IntelliJ, PyCharm, the terminal) push with that sign-in.
  * git's name/email are set to the GitHub name and the private noreply
    address (<id>+<login>@users.noreply.github.com), unless the student set
    their own email.
  * Save: git init (first time, with a .gitignore for Python/Java/C++), commit
    everything, then `gh repo create --private --push` or merge in what was
    saved from another laptop and push. If the two versions clash, nothing is
    lost: the merge is undone and this laptop's version goes to GitHub as a
    separate copy (a branch) for the teacher to help combine.
  * Files over 95 MB are left out (GitHub refuses files over 100 MB).
  * IntelliJ's per-laptop files (.idea/workspace.xml: window layout, run
    settings) never go to GitHub, whatever the project's .gitignore says:
    IntelliJ rewrites them on every start, so they would make the versions
    on two laptops clash.

Testing aids: LAB_GITHUB_GH = the gh program; LAB_GITHUB_APP_ID = application
id; LAB_GITHUB_SELFTEST=1 prints what the window shows after loading, then quits.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

GH = os.environ.get("LAB_GITHUB_GH", "gh")
APP_ID = os.environ.get("LAB_GITHUB_APP_ID", "com.school.SaveToGitHub")
SIGNUP_URL = "https://github.com/signup"
DEVICE_URL = "https://github.com/login/device"
# Where students keep projects (the CS folders come from create-student).
PROJECT_FOLDERS = ["CS/Python", "CS/Java", "CS/C++", "CS/JavaFX", "IdeaProjects", "PycharmProjects", "GitHub"]
DOWNLOAD_FOLDER = "GitHub"
SCAN_DEPTH = 3                    # other git projects are looked for this deep in the home folder
SKIP_FOLDERS = {"snap", "node_modules", "__pycache__", "target", "out", "build", "venv", ".venv"}
MAX_FILE_BYTES = 95 * 1024 * 1024
# Kept on this laptop only (.git/info/exclude), even if a project's .gitignore lists none of them.
LAPTOP_ONLY = ["/.idea/workspace.xml", "/.idea/shelf/", "/.idea/usage.statistics.xml", "/.idea/tasks.xml", "*.iws"]
NOREPLY = "@users.noreply.github.com"

GITIGNORE = """\
# Made by Save to GitHub. Files and folders listed here are not uploaded.
# Python
__pycache__/
*.pyc
.venv/
venv/
# Java (IntelliJ, Maven, Gradle)
*.class
target/
out/
build/
.gradle/
.idea/workspace.xml
.idea/shelf/
.idea/usage.statistics.xml
# C++
*.o
*.out
a.out
# Other
.DS_Store
"""


class StudentError(Exception):
    """Something went wrong; the message is written for a student."""


def env():
    values = dict(os.environ, GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1",
                  GH_SPINNER_DISABLED="1", BROWSER="true", LC_ALL="C.UTF-8")
    values.pop("GIT_ASKPASS", None)
    values.pop("SSH_ASKPASS", None)
    return values


def run(args, cwd=None, check=True, timeout=180):
    try:
        result = subprocess.run(args, cwd=cwd, env=env(), stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=timeout)
    except FileNotFoundError:
        raise StudentError("GitHub tools are not installed on this laptop yet. Ask your teacher.")
    except subprocess.TimeoutExpired:
        raise StudentError("GitHub took too long to answer. Check the Wi-Fi, then try again.")
    if check and result.returncode != 0:
        raise StudentError(friendly(result.stderr + result.stdout))
    return result


def git(path, *args, check=True, timeout=180):
    return run(["git", "-C", path, *args], check=check, timeout=timeout)


def friendly(text):
    """Turn git/gh error output into a sentence a student can act on."""
    low = text.lower()
    if any(words in low for words in ("could not resolve host", "unable to access", "timed out", "connection refused",
                                      "network is unreachable", "error connecting to", "no such host")):
        return "Can't reach GitHub. Check that you're connected to the Wi-Fi, then try again."
    if any(words in low for words in ("authentication failed", "http 401", "bad credentials", "gh auth login",
                                      "not logged in", "could not read username")):
        return "GitHub didn't accept your sign-in. Click Sign out, then sign in again."
    if "file size limit" in low or "large files" in low:
        return "A file is too big for GitHub (over 100 MB). Move it out of the project folder and try again."
    if ("permission" in low and "denied" in low) or "http 403" in low:
        return "GitHub says you aren't allowed to save to this project. Ask your teacher."
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "Something went wrong: " + (" ".join(lines[-2:]) if lines else "no details.")


# ---------------------------------------------------------------- GitHub account

def signed_in():
    """True if this account has a GitHub sign-in saved (no network needed)."""
    return run([GH, "auth", "token", "--hostname", "github.com"], check=False).returncode == 0


def github_user():
    """{"login", "id", "name"} of the signed-in student (needs the network)."""
    data = json.loads(run([GH, "api", "user"], timeout=60).stdout)
    return {"login": data["login"], "id": data["id"], "name": data.get("name") or data["login"]}


def start_sign_in(on_code):
    """Start the browser sign-in. Calls on_code(code) when GitHub hands out the
    one-time code; returns the gh process (wait for it, or kill it to cancel)."""
    process = subprocess.Popen([GH, "auth", "login", "--hostname", "github.com", "--git-protocol", "https",
                                "--web", "--insecure-storage"], env=env(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = []

    def read():
        for line in process.stdout:
            output.append(line)
            match = re.search(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})", line)
            if match:
                on_code(match.group(1))
        process.stdout.close()
        process.output = "".join(output)

    process.reader = threading.Thread(target=read, daemon=True)
    process.reader.start()
    return process


def finish_sign_in():
    """After gh signed in: let git use it, set git's name/email. Returns the user."""
    run([GH, "auth", "setup-git", "--hostname", "github.com"])
    user = github_user()
    set_identity(user)
    return user


def set_identity(user):
    email = run(["git", "config", "--global", "user.email"], check=False).stdout.strip()
    if email and not email.endswith(NOREPLY):
        return                  # the student chose their own; keep it
    run(["git", "config", "--global", "user.email", f"{user['id']}+{user['login']}{NOREPLY}"])
    run(["git", "config", "--global", "user.name", user["name"]])


def sign_out():
    run([GH, "auth", "logout", "--hostname", "github.com"], check=False)


# ---------------------------------------------------------------- projects on this laptop

def has_files(path, limit=2000):
    """True if the folder holds at least one file (looks at most `limit` entries)."""
    seen = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != ".git"]
        if files:
            return True
        seen += len(dirs) + 1
        if seen > limit:
            return False
    return False


def is_repo(path):
    return os.path.exists(os.path.join(path, ".git"))


def find_projects(home):
    """Folders that look like projects: each folder inside the usual project
    folders, a usual folder itself when files sit straight in it (e.g.
    ~/CS/Python/hello.py), and any other git project a few levels down."""
    found = set()
    for relative in PROJECT_FOLDERS:
        parent = os.path.join(home, relative)
        if not os.path.isdir(parent) or os.path.islink(parent):
            continue
        if is_repo(parent):
            found.add(parent)
            continue
        loose_files = False
        for entry in os.scandir(parent):
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                if has_files(entry.path):
                    found.add(entry.path)
            elif entry.is_file(follow_symlinks=False):
                loose_files = True
        if loose_files:
            found.add(parent)
    base_depth = home.rstrip("/").count("/")
    for root, dirs, _ in os.walk(home):
        if ".git" in dirs and root != home:
            found.add(root)
            dirs[:] = []
            continue
        if root.count("/") - base_depth >= SCAN_DEPTH:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_FOLDERS]
    # A folder inside a git project belongs to that project.
    repos = {path for path in found if is_repo(path)}
    projects = [path for path in found
                if not any(path != repo and path.startswith(repo + "/") for repo in repos)]
    return sorted(projects, key=lambda path: (os.path.basename(path).lower(), path))


def origin_url(path):
    if not is_repo(path):
        return None
    url = git(path, "config", "--get", "remote.origin.url", check=False).stdout.strip()
    return url or None


def web_url(remote):
    """https://github.com/owner/name for a GitHub remote, else None."""
    full = full_name(remote)
    return f"https://github.com/{full}" if full else None


def full_name(remote):
    """'owner/name' for a github.com remote URL, else None."""
    if not remote:
        return None
    if remote.startswith("git@github.com:"):
        path = remote.split(":", 1)[1]
    else:
        parsed = urlparse(remote)
        if parsed.hostname != "github.com":
            return None
        path = parsed.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    return "/".join(parts) if len(parts) == 2 and all(parts) else None


def status(path):
    """{"state": new|changes|ahead|behind|both|saved, "changes": n, "remote": url}
    using what was last fetched (no network)."""
    remote = origin_url(path)
    if not remote:
        return {"state": "new", "changes": 0, "remote": None}
    changes = len([line for line in git(path, "status", "--porcelain", check=False).stdout.splitlines() if line])
    counts = git(path, "rev-list", "--left-right", "--count", "HEAD...@{upstream}", check=False)
    if counts.returncode == 0:
        ahead, behind = (int(n) for n in counts.stdout.split())
    else:                       # never uploaded from here (or no commits yet)
        ahead, behind = 1, 0
    if changes or ahead:
        state = "both" if behind else ("changes" if changes else "ahead")
    else:
        state = "behind" if behind else "saved"
    return {"state": state, "changes": changes, "remote": remote}


def check_online(path):
    """Fetch, so status() knows about saves from other laptops."""
    if origin_url(path):
        git(path, "fetch", "--quiet", "origin", check=False, timeout=60)


def describe(info):
    changes = info["changes"]
    files = f"{changes} file{'s' if changes != 1 else ''}"
    return {
        "new": ("Not on GitHub yet", "Save to GitHub"),
        "changes": (f"{files} changed since your last save", "Save to GitHub"),
        "ahead": ("Saved on this laptop but not uploaded yet", "Save to GitHub"),
        "behind": ("A newer version is on GitHub (saved on another laptop)", "Get latest"),
        "both": (f"{files} changed here, and a newer version is on GitHub", "Save to GitHub"),
        "saved": ("Saved on GitHub ✓", None),
    }[info["state"]]


# ---------------------------------------------------------------- saving

def repo_name(path, home):
    name = os.path.basename(path.rstrip("/"))
    if os.path.dirname(path) == os.path.join(home, "CS"):
        name = "CS-" + name                    # ~/CS/Python itself → CS-Python
    name = name.replace("++", "pp").replace("#", "sharp")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return name[:90] or "my-project"


def free_name(login, name):
    """name, or name-2, name-3… if the student already has a project called that."""
    candidate, number = name, 1
    while run([GH, "repo", "view", f"{login}/{candidate}", "--json", "name"], check=False,
              timeout=60).returncode == 0:
        number += 1
        candidate = f"{name}-{number}"
    return candidate


def nested_projects(path):
    inside = []
    for root, dirs, _ in os.walk(path):
        if root != path and ".git" in dirs:
            inside.append(os.path.relpath(root, path))
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d != ".git"]
    return inside


def keep_laptop_files_local(path):
    """Exclude IntelliJ's per-laptop files, and stop tracking them if a project
    (e.g. from GitHub Classroom) already has them. The files themselves stay."""
    exclude = os.path.join(path, ".git", "info", "exclude")
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    try:
        with open(exclude, encoding="utf-8") as handle:
            present = set(handle.read().splitlines())
    except FileNotFoundError:
        present = set()
    missing = [pattern for pattern in LAPTOP_ONLY if pattern not in present]
    if missing:
        with open(exclude, "a", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in missing))
    tracked = git(path, "ls-files", "-z", "--", *[p.lstrip("/") for p in LAPTOP_ONLY], check=False).stdout
    if tracked.strip("\0"):
        git(path, "rm", "-r", "--cached", "--quiet", "--ignore-unmatch", "--",
            *[p.lstrip("/") for p in LAPTOP_ONLY])


def leave_out_big_files(path):
    """Add new files over the GitHub limit to .git/info/exclude; returns them."""
    listed = git(path, "ls-files", "-z", "--others", "--exclude-standard").stdout.split("\0")
    big = [name for name in listed if name and os.path.getsize(os.path.join(path, name)) > MAX_FILE_BYTES]
    if big:
        exclude = os.path.join(path, ".git", "info", "exclude")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as handle:
            handle.write("".join("/" + name.replace("\\", "\\\\") + "\n" for name in big))
    return big


def commit_message(note):
    stamp = time.strftime("%Y-%m-%d %H:%M")
    message = f"Saved from {socket.gethostname()} on {stamp}"
    return f"{note.strip()}\n\n{message}" if note and note.strip() else message


def commit_all(path, note):
    git(path, "add", "--all")
    if git(path, "diff", "--cached", "--quiet", check=False).returncode != 0:
        git(path, "commit", "--quiet", "-m", commit_message(note))


def save(path, user, home, note=""):
    """Save a project to GitHub. Returns a dict with "message" (for the student),
    "url" and, when the versions clashed, "copy" (the branch name)."""
    path = os.path.realpath(path)
    home = os.path.realpath(home)
    if path == home or not path.startswith(home + "/"):
        raise StudentError("Pick a project folder inside your home folder (not the home folder itself).")
    if not is_repo(path):
        inside = nested_projects(path)
        if inside:
            raise StudentError("This folder has projects inside it that use GitHub already ("
                               + ", ".join(inside[:3]) + "). Save those one at a time instead.")
        if not has_files(path):
            raise StudentError("This folder is empty. Save a file in it first.")
        git(path, "init", "--quiet", "-b", "main")
        gitignore = os.path.join(path, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w", encoding="utf-8") as handle:
                handle.write(GITIGNORE)
    keep_laptop_files_local(path)
    big = leave_out_big_files(path)
    commit_all(path, note)
    if git(path, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode != 0:
        raise StudentError("This folder is empty. Save a file in it first.")
    left_out = (" Left out (too big for GitHub): " + ", ".join(big[:3]) + ".") if big else ""

    remote = origin_url(path)
    if not remote:
        name = free_name(user["login"], repo_name(path, home))
        run([GH, "repo", "create", name, "--private", "--source", path, "--remote", "origin", "--push"])
        remote = origin_url(path)
        renamed = "" if name == repo_name(path, home) else \
            f" You already had a project with that name, so this one is called {name}."
        return {"message": f"Saved as a new private project on GitHub: {name}.{renamed}{left_out}",
                "url": web_url(remote)}

    branch = git(path, "symbolic-ref", "--short", "--quiet", "HEAD", check=False).stdout.strip()
    if not branch:
        raise StudentError("This project is in an unusual state (no branch). Ask your teacher.")
    git(path, "fetch", "--quiet", "origin", timeout=120)
    if git(path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", check=False).returncode == 0:
        merged = git(path, "merge", "--no-edit", "--quiet", f"origin/{branch}", check=False)
        if merged.returncode != 0:
            git(path, "merge", "--abort", check=False)
            copy = "copy-from-" + re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().lower()) + time.strftime("-%Y%m%d-%H%M")
            git(path, "push", "--quiet", "origin", f"HEAD:refs/heads/{copy}")
            return {"message": "This project was also changed on another laptop, and the two versions clash. "
                               f"Nothing is lost: this laptop's version is on GitHub as a separate copy called "
                               f"\"{copy}\". Ask your teacher to help combine them.{left_out}",
                    "url": web_url(remote), "copy": copy}
    git(path, "push", "--quiet", "--set-upstream", "origin", branch)
    return {"message": f"Saved on GitHub ✓{left_out}", "url": web_url(remote)}


# ---------------------------------------------------------------- projects on GitHub

def github_projects():
    """The student's own projects plus ones shared with them (e.g. GitHub Classroom)."""
    output = run([GH, "api", "--paginate",
                  "user/repos?per_page=100&sort=updated&affiliation=owner,collaborator,organization_member",
                  "--jq", ".[] | {full_name, name, clone_url, html_url, private}"], timeout=120).stdout
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def download(project, home):
    """Clone a project into ~/GitHub/<name> (or <name>-2…). Returns the folder."""
    parent = os.path.join(home, DOWNLOAD_FOLDER)
    os.makedirs(parent, exist_ok=True)
    target = os.path.join(parent, project["name"])
    number = 1
    while os.path.exists(target):
        number += 1
        target = os.path.join(parent, f"{project['name']}-{number}")
    run(["git", "clone", "--quiet", project["clone_url"], target], timeout=600)
    keep_laptop_files_local(target)
    return target


# ---------------------------------------------------------------- the window

def main():
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gio, GLib, Gtk

    home = os.path.expanduser("~")
    selftest = os.environ.get("LAB_GITHUB_SELFTEST")     # "1", or "download" to open that list

    css = Gtk.CssProvider()
    css.load_from_data(b"""
        .big-title { font-size: 20pt; font-weight: bold; }
        .step { font-size: 14pt; font-weight: bold; }
        .code { font-size: 32pt; font-weight: bold; font-family: monospace; letter-spacing: 4px; }
        .project-name { font-size: 13pt; font-weight: bold; }
        .dim { opacity: 0.7; }
        .message { font-size: 12pt; }
    """)

    def label(text, css_class=None, wrap=True, xalign=0.0, **properties):
        widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, **properties)
        if css_class:
            for name in css_class.split():
                widget.add_css_class(name)
        return widget

    def background(work, done):
        def runner():
            try:
                result, error = work(), None
            except StudentError as problem:
                result, error = None, str(problem)
            except Exception as problem:                     # never leave the window stuck
                result, error = None, f"Something went wrong: {problem}"
            GLib.idle_add(lambda: done(result, error) and False)
        threading.Thread(target=runner, daemon=True).start()

    def open_uri(uri):
        Gtk.UriLauncher.new(uri).launch(window, None, None)

    class Window(Gtk.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Save to GitHub", default_width=780, default_height=660)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.user = None
            self.busy = False
            self.sign_in_process = None
            self.buttons = []           # the page buttons
            self.row_buttons = []       # one per project row

            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                            margin_start=18, margin_end=18)
            outer.append(label("Save to GitHub", "big-title"))
            outer.append(label("Keep your code safe online, and get it back on any lab laptop.", "dim"))
            self.stack = Gtk.Stack(vexpand=True)
            self.stack.add_named(self.loading_page(), "loading")
            self.stack.add_named(self.sign_in_page(), "signin")
            self.stack.add_named(self.projects_page(), "projects")
            outer.append(self.stack)
            self.message = label("", "message")
            self.message.set_selectable(True)
            outer.append(self.message)
            self.set_child(outer)
            self.connect("close-request", self.on_close)
            self.refresh()

        # ---- pages
        def loading_page(self):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
            spinner = Gtk.Spinner(spinning=True)
            box.append(spinner)
            box.append(label("Loading…", xalign=0.5))
            return box

        def sign_in_page(self):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.append(label("Step 1: Get a free GitHub account", "step"))
            box.append(label("Skip this if you already have one. Use an email you can open right now: "
                             "GitHub sends a code to it."))
            signup = Gtk.Button(label="Make a GitHub account", halign=Gtk.Align.START)
            signup.connect("clicked", lambda _b: open_uri(SIGNUP_URL))
            box.append(signup)
            box.append(Gtk.Separator(margin_top=8, margin_bottom=8))
            box.append(label("Step 2: Connect this laptop to your GitHub account", "step"))
            box.append(label("You do this once on each laptop you use."))
            self.sign_in_button = Gtk.Button(label="Sign in to GitHub", halign=Gtk.Align.START)
            self.sign_in_button.add_css_class("suggested-action")
            self.sign_in_button.connect("clicked", self.on_sign_in)
            box.append(self.sign_in_button)

            self.code_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, visible=False, margin_top=8)
            self.code_box.append(label("Your code:"))
            self.code_label = label("", "code", xalign=0.0)
            self.code_label.set_selectable(True)
            self.code_box.append(self.code_label)
            copy_open = Gtk.Button(label="Copy the code and open GitHub", halign=Gtk.Align.START)
            copy_open.add_css_class("suggested-action")
            copy_open.connect("clicked", self.on_copy_and_open)
            self.code_box.append(copy_open)
            self.code_box.append(label("On the GitHub page: sign in if it asks, paste the code (Ctrl+V), click "
                                       "Continue, then click the green Authorize button. "
                                       "Come back here when it says you're done."))
            waiting = Gtk.Box(spacing=8)
            waiting.append(Gtk.Spinner(spinning=True))
            waiting.append(label("Waiting for GitHub…"))
            cancel = Gtk.Button(label="Cancel")
            cancel.connect("clicked", lambda _b: self.cancel_sign_in())
            waiting.append(cancel)
            self.code_box.append(waiting)
            box.append(self.code_box)
            return box

        def projects_page(self):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            account = Gtk.Box(spacing=12)
            self.account_label = label("")
            self.account_label.set_hexpand(True)
            account.append(self.account_label)
            sign_out_button = Gtk.Button(label="Sign out")
            sign_out_button.connect("clicked", self.on_sign_out)
            account.append(sign_out_button)
            self.buttons.append(sign_out_button)
            box.append(account)
            box.append(label("Your projects on this laptop", "step"))
            self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            self.list.add_css_class("boxed-list")
            scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroller.set_child(self.list)
            box.append(scroller)
            note_row = Gtk.Box(spacing=8)
            note_row.append(label("Note for your next save (optional):", wrap=False))
            self.note = Gtk.Entry(hexpand=True, placeholder_text="e.g. Finished question 3")
            note_row.append(self.note)
            box.append(note_row)
            actions = Gtk.Box(spacing=8)
            for text, handler in (("Get a project from GitHub…", self.on_get_project),
                                  ("Save a different folder…", self.on_choose_folder),
                                  ("Refresh", lambda _b: self.refresh())):
                button = Gtk.Button(label=text)
                button.connect("clicked", handler)
                actions.append(button)
                self.buttons.append(button)
            box.append(actions)
            return box

        # ---- state
        def say(self, text):
            self.message.set_label(text or "")

        def set_busy(self, busy, text=None):
            self.busy = busy
            for button in self.buttons + self.row_buttons:
                button.set_sensitive(not busy)
            if text is not None:
                self.say(text)

        def refresh(self, then_message=None):
            self.stack.set_visible_child_name("loading")

            def work():
                if not signed_in():
                    return None
                try:
                    user = github_user()
                except StudentError as problem:
                    return {"login": None, "problem": str(problem)}
                return user

            def done(user, error):
                if error:
                    self.say(error)
                if not user:
                    self.stack.set_visible_child_name("signin")
                    self.selftest_report()
                    return
                self.user = user if user.get("login") else None
                if self.user:
                    self.account_label.set_markup(
                        f"Signed in to GitHub as <b>{GLib.markup_escape_text(user['login'])}</b>")
                else:
                    self.account_label.set_label("Signed in to GitHub (can't check right now)")
                    self.say(user.get("problem"))
                self.stack.set_visible_child_name("projects")
                self.load_projects(then_message)
            background(work, done)

        def load_projects(self, then_message=None):
            def work():
                return [(path, status(path)) for path in find_projects(home)]

            def done(projects, error):
                self.show_projects(projects or [])
                if error or then_message:
                    self.say(error or then_message)
                self.selftest_report()
                if projects and self.user:
                    self.check_online([path for path, info in projects if info["remote"]])
            background(work, done)

        def check_online(self, paths):
            def work():
                for path in paths:
                    check_online(path)
                return [(path, status(path)) for path in find_projects(home)]

            def done(projects, error):
                if projects is not None and not self.busy:
                    self.show_projects(projects)
            background(work, done)

        def show_projects(self, projects):
            self.row_buttons = []
            while (row := self.list.get_row_at_index(0)) is not None:
                self.list.remove(row)
            if not projects:
                self.list.append(label("No projects found yet. Save some code in your CS folder, or click "
                                       "\"Save a different folder…\".", xalign=0.0))
            self.shown = []
            for path, info in projects:
                text, action = describe(info)
                row = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
                names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
                names.append(label(os.path.basename(path), "project-name"))
                names.append(label(path.replace(home, "~", 1), "dim"))
                names.append(label(text))
                row.append(names)
                if action:
                    button = Gtk.Button(label=action, valign=Gtk.Align.CENTER)
                    button.add_css_class("suggested-action")
                    button.connect("clicked", self.on_save, path, info)
                    button.set_sensitive(not self.busy)
                    row.append(button)
                    self.row_buttons.append(button)
                url = web_url(info["remote"])
                if url:
                    view = Gtk.Button(label="Open on GitHub", valign=Gtk.Align.CENTER)
                    view.connect("clicked", lambda _b, u=url: open_uri(u))
                    row.append(view)
                self.list.append(row)
                self.shown.append({"name": os.path.basename(path), "status": text, "button": action})

        def selftest_report(self):
            if selftest == "download" and self.stack.get_visible_child_name() == "projects":
                self.on_get_project(None)
            elif selftest:
                print(json.dumps({"page": self.stack.get_visible_child_name(),
                                  "projects": getattr(self, "shown", []),
                                  "message": self.message.get_label()}), flush=True)
                self.get_application().quit()

        # ---- sign in / out
        def on_sign_in(self, _button):
            self.sign_in_button.set_sensitive(False)
            self.say("Asking GitHub for a code…")

            def got_code(code):
                GLib.idle_add(self.show_code, code)

            self.sign_in_process = process = start_sign_in(got_code)

            def work():
                process.wait()
                process.reader.join(timeout=5)
                if process.returncode != 0:
                    if getattr(process, "cancelled", False):
                        return None
                    raise StudentError(friendly(getattr(process, "output", "")))
                return finish_sign_in()

            def done(user, error):
                self.sign_in_process = None
                self.code_box.set_visible(False)
                self.sign_in_button.set_sensitive(True)
                if error:
                    self.say(error)
                elif user:
                    self.refresh(f"You're signed in as {user['login']}. "
                                 "Now click Save to GitHub next to a project.")
                else:
                    self.say("")
            background(work, done)

        def show_code(self, code):
            self.code_label.set_label(code)
            self.code_box.set_visible(True)
            self.say("")
            return False

        def on_copy_and_open(self, _button):
            self.get_clipboard().set(self.code_label.get_label())
            open_uri(DEVICE_URL)

        def cancel_sign_in(self):
            if self.sign_in_process and self.sign_in_process.poll() is None:
                self.sign_in_process.cancelled = True
                self.sign_in_process.kill()

        def on_sign_out(self, _button):
            dialog = Gtk.AlertDialog(message="Sign out of GitHub on this laptop?",
                                     detail="Your projects stay on this laptop and on GitHub. "
                                            "You'll need to sign in again to save.",
                                     buttons=["Cancel", "Sign out"], cancel_button=0, default_button=1)

            def answered(dialog, result):
                try:
                    if dialog.choose_finish(result) != 1:
                        return
                except GLib.Error:
                    return
                self.set_busy(True, "Signing out…")
                background(sign_out, lambda _r, _e: (self.set_busy(False, "Signed out."), self.refresh()))
            dialog.choose(self, None, answered)

        def on_close(self, _window):
            self.cancel_sign_in()
            return False

        # ---- saving
        def on_save(self, _button, path, info):
            if self.busy:
                return
            if not self.user:
                self.say("Can't reach GitHub right now. Check the Wi-Fi, then click Refresh.")
                return
            if info["state"] == "new":
                name = repo_name(path, home)
                dialog = Gtk.AlertDialog(message=f"Put \"{os.path.basename(path)}\" on GitHub?",
                                         detail=f"It will be a private project called {name}: only you can see it.",
                                         buttons=["Cancel", "Save to GitHub"], cancel_button=0, default_button=1)

                def answered(dialog, result):
                    try:
                        if dialog.choose_finish(result) == 1:
                            self.do_save(path)
                    except GLib.Error:
                        pass
                dialog.choose(self, None, answered)
            else:
                self.do_save(path)

        def do_save(self, path):
            note = self.note.get_text()
            self.set_busy(True, f"Saving {os.path.basename(path)} to GitHub…")

            def done(result, error):
                self.set_busy(False)
                if result:
                    self.note.set_text("")
                self.load_projects(error or result["message"])
            background(lambda: save(path, self.user, home, note), done)

        def on_choose_folder(self, _button):
            dialog = Gtk.FileDialog(title="Choose the project folder to save", modal=True)
            dialog.set_initial_folder(Gio.File.new_for_path(home))

            def chosen(dialog, result):
                try:
                    folder = dialog.select_folder_finish(result)
                except GLib.Error:
                    return
                if folder and folder.get_path():
                    path = folder.get_path()
                    self.on_save(None, path, status(path) if is_repo(path) else {"state": "new"})
            dialog.select_folder(self, None, chosen)

        # ---- downloading
        def on_get_project(self, _button):
            if not self.user:
                self.say("Can't reach GitHub right now. Check the Wi-Fi, then click Refresh.")
                return
            self.set_busy(True, "Getting your list of projects from GitHub…")

            def work():
                here = {(full_name(origin_url(path)) or "").lower() for path in find_projects(home)}
                return github_projects(), here

            def done(result, error):
                self.set_busy(False, error or "")
                if result:
                    self.show_download_window(*result)
            background(work, done)

        def show_download_window(self, projects, here):
            chooser = Gtk.Window(title="Get a project from GitHub", transient_for=self, modal=True,
                                 default_width=620, default_height=480)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=16, margin_bottom=16,
                          margin_start=16, margin_end=16)
            box.append(label("Your projects on GitHub", "step"))
            box.append(label("Download one to work on it on this laptop. It goes in your GitHub folder."))
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroller.set_child(listbox)
            box.append(scroller)
            if not projects:
                listbox.append(label("You don't have any projects on GitHub yet."))
            shown = []
            for project in projects:
                row = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=8, margin_end=8)
                owner = project["full_name"].split("/")[0]
                text = project["name"] + ("" if self.user and owner.lower() == self.user["login"].lower()
                                          else f"  (from {owner})")
                row.append(label(text, hexpand=True))
                if project["full_name"].lower() in here:
                    row.append(label("Already on this laptop", "dim", wrap=False))
                    shown.append({"name": text, "button": None})
                else:
                    button = Gtk.Button(label="Download")
                    button.connect("clicked", lambda _b, p=project: (chooser.close(), self.do_download(p)))
                    row.append(button)
                    shown.append({"name": text, "button": "Download"})
                listbox.append(row)
            close = Gtk.Button(label="Close", halign=Gtk.Align.END)
            close.connect("clicked", lambda _b: chooser.close())
            box.append(close)
            chooser.set_child(box)
            chooser.present()
            if selftest:
                print(json.dumps({"page": "download", "projects": shown, "message": self.message.get_label()}),
                      flush=True)
                self.get_application().quit()

        def do_download(self, project):
            self.set_busy(True, f"Downloading {project['name']}…")

            def done(folder, error):
                self.set_busy(False)
                if folder:
                    shown = folder.replace(home, "~", 1)
                    self.load_projects(f"Downloaded {project['name']} to {shown}. Open that folder in your "
                                       "editor (File → Open). Click Save to GitHub here when you're done.")
                else:
                    self.say(error)
            background(lambda: download(project, home), done)

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

        def do_activate(self):
            nonlocal window
            if window is None:
                window = Window(self)
            window.present()

    window = None
    return App().run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
