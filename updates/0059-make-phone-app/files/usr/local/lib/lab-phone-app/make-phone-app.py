#!/usr/bin/env python3
"""Make a Phone App (update 0059): send a JavaFX project to the teacher's build service.

The teacher's computer turns student JavaFX projects into Android apps (the build
service, "fx2android-service"; the lab laptops are too small to build them). This
window is the student's side (the teacher's choices, 2026-11-13):
  * A menu app that lists the student's Java projects (~/IdeaProjects and the CS
    folders); they pick one and type an app name.
  * The student types the class code from the board. The update repo is public, so
    the code can't be built in; it is remembered for the student's next send
    (~/.config/lab-phone-app/class-code).
  * The laptop adds the student number and the laptop name (request headers, so
    they stay out of address logs); the teacher's status page shows who sent what.
  * After sending: the place in line, then a big QR code to scan with a phone and a
    button that opens the app's page in the browser.

The project is zipped without target/, out/, build/, .git, .idea and the like.
The service address: SERVER in /etc/lab-phone-app/config.

Testing aids: LAB_PHONEAPP_CONFIG = config file; LAB_PHONEAPP_SELFTEST=1 prints the
project list and quits; LAB_PHONEAPP_SELFTEST=send:<folder> also sends that folder
with the remembered class code, prints each status and quits when it is finished;
LAB_PHONEAPP_SHOW_JOB=<id> opens the window on that job's page (screenshots).
"""

import getpass
import json
import os
import re
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

CONFIG = os.environ.get("LAB_PHONEAPP_CONFIG", "/etc/lab-phone-app/config")
APP_ID = "com.school.MakePhoneApp"
PROJECT_FOLDERS = ["IdeaProjects", "CS/JavaFX", "CS/Java"]
SKIP = {"target", "out", "build", "bin", ".git", ".idea", ".gradle", ".mvn", "node_modules", "__pycache__",
        ".venv", "venv", ".vscode", ".settings"}
SKIP_FILES = (".class", ".iml", ".jar.tmp", ".log")
MAX_ZIP = 240 * 1024 * 1024        # the service takes up to 250 MB
CODE_FILE = os.path.expanduser("~/.config/lab-phone-app/class-code")


class StudentError(Exception):
    """Something went wrong; the message is written for a student."""


# ---------------------------------------------------------------- the work (no window)

def server():
    values = {}
    try:
        with open(CONFIG) as fh:
            for line in fh:
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
    except OSError:
        pass
    address = values.get("SERVER", "").rstrip("/")
    if not address.startswith("https://") and not address.startswith("http://"):
        raise StudentError("This laptop doesn't know where to send apps yet. Ask your teacher.")
    return address


def java_files(folder, limit=4000):
    """The .java files in a project (skipping build folders), at most `limit`."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        found += [os.path.join(root, f) for f in files if f.endswith(".java")]
        if len(found) >= limit:
            break
    return found


def uses_javafx(folder, files):
    for path in [os.path.join(folder, "pom.xml"), os.path.join(folder, "build.gradle")] + files[:200]:
        try:
            with open(path, errors="replace") as fh:
                if "javafx" in fh.read(400_000):
                    return True
        except OSError:
            pass
    return False


def find_projects(home):
    """[(folder, is_javafx, modified time)] for each Java project in the usual places, newest first."""
    projects = []
    seen = set()
    for relative in PROJECT_FOLDERS:
        parent = os.path.join(home, relative)
        if not os.path.isdir(parent) or os.path.islink(parent):
            continue
        for entry in os.scandir(parent):
            if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                continue
            real = os.path.realpath(entry.path)
            if real in seen:
                continue
            files = java_files(entry.path)
            if files:
                seen.add(real)
                newest = max(os.path.getmtime(f) for f in files[:500])
                projects.append((entry.path, uses_javafx(entry.path, files), newest))
    projects.sort(key=lambda p: (not p[1], -p[2]))
    return projects


def make_zip(folder, dest):
    """Zip the project under its folder name, leaving out build output and IDE files."""
    top = os.path.basename(folder.rstrip("/")) or "project"
    total = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not os.path.islink(os.path.join(root, d)))
            for name in sorted(files):
                path = os.path.join(root, name)
                if name.endswith(SKIP_FILES) or os.path.islink(path) or not os.path.isfile(path):
                    continue
                total += os.path.getsize(path)
                if total > MAX_ZIP:
                    raise StudentError("This project is too big to send (over 240 MB). Remove big videos or "
                                       "other large files you don't use, then try again.")
                z.write(path, os.path.join(top, os.path.relpath(path, folder)))
    return dest


def student_number():
    user = getpass.getuser()
    return user[5:] if user.startswith("tdsb-") else user


def read_code():
    try:
        with open(CODE_FILE) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def save_code(code):
    try:
        os.makedirs(os.path.dirname(CODE_FILE), exist_ok=True)
        fd = os.open(CODE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(code + "\n")
    except OSError:
        pass


def request(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as reply:
            return reply.read()
    except urllib.error.HTTPError as problem:
        try:
            message = json.loads(problem.read()).get("error", "")
        except Exception:
            message = ""
        if problem.code == 403:
            raise StudentError(message or "Wrong class code. Check the code on the board.")
        if problem.code in (502, 503, 504) and not message:
            raise StudentError("The app maker on the teacher's computer is not running right now. Ask your teacher.")
        raise StudentError(message or f"The app maker answered with an error ({problem.code}). Ask your teacher.")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
        raise StudentError("Can't reach the app maker. Check that you are on the Wi-Fi, then try again.")


def send(folder, name, code):
    """Zip and upload; returns the service's answer (id, url, state, error)."""
    code = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    if not code:
        raise StudentError("Type the class code from the board first.")
    base = server()
    with tempfile.TemporaryDirectory(prefix="phone-app-") as tmp:
        zip_path = make_zip(folder, os.path.join(tmp, "project.zip"))
        with open(zip_path, "rb") as fh:
            body = fh.read()
    query = urllib.parse.urlencode({"code": code, "name": name})
    headers = {"Content-Type": "application/zip", "X-Lab-Student": student_number(),
               "X-Lab-Laptop": socket.gethostname()}
    answer = json.loads(request(f"{base}/upload?{query}", data=body, headers=headers, timeout=600))
    save_code(code)                     # the code worked: remember it
    return answer


def job_status(job_id):
    return json.loads(request(f"{server()}/a/{urllib.parse.quote(job_id)}.json"))


def qr_picture(job_id):
    return request(f"{server()}/a/{urllib.parse.quote(job_id)}/qr.svg")


def wait_text(status):
    if status["state"] == "building":
        return "Your app is being built now. This takes about 2 minutes."
    ahead = status.get("ahead", 0)
    if ahead == 0:
        return "Your project is next in line."
    return f"{ahead} project{'s' if ahead != 1 else ''} ahead of yours (about {2 * (ahead + 1)} minutes)."


# ---------------------------------------------------------------- self-test (no window)

def selftest(mode):
    for folder, fx, _ in find_projects(os.path.expanduser("~")):
        print(("JavaFX " if fx else "Java   ") + folder)
    if mode.startswith("send:"):
        import time
        answer = send(mode[5:], os.path.basename(mode[5:].rstrip("/")), read_code())
        print("sent:", answer)
        while answer.get("state") in ("queued", "building"):
            time.sleep(5)
            answer = job_status(answer["id"]) | {"id": answer["id"]}
            print("status:", answer["state"], "-", answer["url"] if answer["state"] == "ready" else
                  answer.get("error") if answer["state"] == "failed" else wait_text(answer))
        if answer["state"] == "ready":
            print("qr bytes:", len(qr_picture(answer["id"])))
        else:
            print("error:", answer.get("error"))


# ---------------------------------------------------------------- the window

def main():
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    home = os.path.expanduser("~")
    css = Gtk.CssProvider()
    css.load_from_data(b"""
        .big-title { font-size: 20pt; font-weight: bold; }
        .step { font-size: 14pt; font-weight: bold; }
        .project-name { font-size: 13pt; font-weight: bold; }
        .dim { opacity: 0.7; }
        .message { font-size: 12pt; }
        .bad { color: #c01c28; font-weight: bold; }
        .good { color: #26a269; font-size: 16pt; font-weight: bold; }
        .qr { background: white; padding: 8px; }
    """)

    def label(text, css_class=None, wrap=True, xalign=0.0, **properties):
        widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, **properties)
        for name in (css_class or "").split():
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

    class Window(Gtk.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Make a Phone App", default_width=760, default_height=680)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.chosen = None
            self.job_id = None
            self.url = None
            self.poll = None
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                            margin_start=18, margin_end=18)
            outer.append(label("Make a Phone App", "big-title"))
            outer.append(label("Turn your JavaFX project into an Android app you can put on your phone.", "dim"))
            self.stack = Gtk.Stack(vexpand=True)
            self.stack.add_named(self.choose_page(), "choose")
            self.stack.add_named(self.wait_page(), "wait")
            outer.append(self.stack)
            self.set_child(outer)
            self.connect("close-request", lambda _w: self.stop_polling() or False)
            self.load_projects()
            if os.environ.get("LAB_PHONEAPP_SHOW_JOB"):        # testing aid (see the top of the file)
                self.chosen = home
                self.sent({"id": os.environ["LAB_PHONEAPP_SHOW_JOB"], "state": "queued"}, None)
                self.check()

        # ---- page 1: choose a project, name it, class code, send
        def choose_page(self):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.append(label("1. Choose your project", "step"))
            self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            self.list.add_css_class("boxed-list")
            self.list.connect("row-selected", self.on_row)
            scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroller.set_child(self.list)
            box.append(scroller)

            grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_top=6)
            grid.attach(label("2. Name of your app", "step"), 0, 0, 1, 1)
            self.name = Gtk.Entry(max_length=40, hexpand=True, placeholder_text="For example: Laptop Inventory")
            grid.attach(self.name, 1, 0, 1, 1)
            grid.attach(label("3. Class code", "step"), 0, 1, 1, 1)
            self.code = Gtk.Entry(max_length=12, hexpand=True, placeholder_text="The code on the board",
                                  text=read_code())
            self.code.connect("activate", self.on_send)
            grid.attach(self.code, 1, 1, 1, 1)
            box.append(grid)

            self.send_button = Gtk.Button(label="Make my app", halign=Gtk.Align.START, sensitive=False)
            self.send_button.add_css_class("suggested-action")
            self.send_button.connect("clicked", self.on_send)
            sending = Gtk.Box(spacing=10)
            sending.append(self.send_button)
            self.spinner = Gtk.Spinner()
            sending.append(self.spinner)
            box.append(sending)
            self.message = label("", "message")
            self.message.set_selectable(True)
            box.append(self.message)
            return box

        def load_projects(self):
            self.message.set_text("Looking for your projects…")
            background(lambda: find_projects(home), self.show_projects)

        def show_projects(self, projects, error):
            self.message.set_text(error or "")
            if not projects and not error:
                self.message.set_text("No Java projects found in IdeaProjects or your CS folders. Make your "
                                      "project in IntelliJ first (it saves to IdeaProjects).")
            for folder, fx, _ in projects or []:
                row = Gtk.ListBoxRow()
                row.folder = folder
                inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=8, margin_bottom=8,
                                margin_start=10, margin_end=10)
                inner.append(label(os.path.basename(folder), "project-name"))
                where = folder.replace(home, "~", 1)
                inner.append(label(where if fx else f"{where}  ·  not JavaFX: only JavaFX projects can become "
                                   "phone apps", "dim"))
                row.set_child(inner)
                self.list.append(row)

        def on_row(self, _list, row):
            self.chosen = row.folder if row else None
            if row and (not self.name.get_text() or getattr(self, "auto_name", "") == self.name.get_text()):
                self.auto_name = os.path.basename(row.folder)[:40]
                self.name.set_text(self.auto_name)
            self.send_button.set_sensitive(row is not None)

        def on_send(self, *_args):
            if not self.chosen or self.spinner.get_spinning():
                return
            name = self.name.get_text().strip() or os.path.basename(self.chosen)
            folder, code = self.chosen, self.code.get_text()
            self.send_button.set_sensitive(False)
            self.spinner.start()
            self.message.set_text("Packing and sending your project…")
            background(lambda: send(folder, name, code), self.sent)

        def sent(self, answer, error):
            self.spinner.stop()
            self.send_button.set_sensitive(True)
            if error:
                self.message.set_text(error)
                return
            self.message.set_text("")
            self.job_id, self.url = answer["id"], answer.get("url")
            self.app_title.set_text(self.name.get_text().strip() or os.path.basename(self.chosen))
            self.show_status(answer)
            self.stack.set_visible_child_name("wait")
            if answer["state"] in ("queued", "building"):
                self.poll = GLib.timeout_add_seconds(5, self.check)

        # ---- page 2: in line → QR code (or why it failed)
        def wait_page(self):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self.app_title = label("", "step")
            box.append(self.app_title)
            self.waiting = Gtk.Box(spacing=10)
            self.waiting.append(Gtk.Spinner(spinning=True))
            self.wait_label = label("")
            self.waiting.append(self.wait_label)
            box.append(self.waiting)
            self.state_label = label("", "message")
            self.state_label.set_selectable(True)
            box.append(self.state_label)
            self.qr = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN, vexpand=True,
                                  halign=Gtk.Align.CENTER, visible=False)
            self.qr.set_size_request(300, 300)
            self.qr.add_css_class("qr")
            box.append(self.qr)
            buttons = Gtk.Box(spacing=10)
            self.open_button = Gtk.Button(label="Open my app's page", visible=False)
            self.open_button.add_css_class("suggested-action")
            self.open_button.connect("clicked", lambda _b: Gtk.UriLauncher.new(self.url).launch(self, None, None))
            buttons.append(self.open_button)
            again = Gtk.Button(label="Send another project")
            again.connect("clicked", self.on_again)
            buttons.append(again)
            box.append(buttons)
            return box

        def check(self):
            job_id = self.job_id
            background(lambda: job_status(job_id), lambda status, error: job_id == self.job_id
                       and self.show_status(status, error))
            return True

        def show_status(self, status, error=None):
            if error:                                           # keep waiting; show the problem
                self.state_label.set_text(error)
                return
            state = status["state"]
            self.url = status.get("url") or self.url
            self.waiting.set_visible(state in ("queued", "building"))
            self.open_button.set_visible(state != "failed" and bool(self.url))
            if state in ("queued", "building"):
                self.wait_label.set_text(wait_text(status))
                self.state_label.set_text("You can keep working. This window updates by itself.")
                return
            self.stop_polling()
            if state == "failed":
                self.state_label.set_text("This project could not be turned into a phone app:\n\n"
                                          + (status.get("error") or "no reason given"))
                return
            self.state_label.set_text("Your app is ready! Scan this with your phone's camera to download it "
                                      "(Android phones only), or open the page.")
            job_id = self.job_id
            background(lambda: qr_picture(job_id), self.show_qr)

        def show_qr(self, svg, error):
            if error or not svg:
                return
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(svg))
                self.qr.set_paintable(texture)
                self.qr.set_visible(True)
            except Exception:
                pass                                            # the page button still works

        def on_again(self, _button):
            self.stop_polling()
            self.job_id = None
            self.qr.set_visible(False)
            self.stack.set_visible_child_name("choose")

        def stop_polling(self):
            if self.poll:
                GLib.source_remove(self.poll)
                self.poll = None

    app = Gtk.Application(application_id=APP_ID)

    def activate(application):
        window = application.get_active_window() or Window(application)
        window.present()
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    mode = os.environ.get("LAB_PHONEAPP_SELFTEST")
    if mode:
        try:
            selftest(mode)
        except StudentError as problem:
            print("student error:", problem)
            sys.exit(1)
        sys.exit(0)
    sys.exit(main())
