#!/usr/bin/env python3
"""Class poll window (update 0024): one multiple-choice question from the teacher.

Usage: poll-window.py /run/lab-messages/poll-<id>.json
       ({"id", "question", "options", "closed", "counts", "answered"}; written by
       lab-messages-listener.py, which starts this in every logged-in session)

The teacher's choices (2026-10-18):
  * The student can change their answer until the teacher closes the poll;
    only the last one counts.
  * The window can't be closed before answering.
  * When the poll closes, the window turns into the results (bars and
    percentages, no names). If the student had closed it, it opens again.
  * Correct answers (update 0025, optional, one or more): sent only with the
    results. The correct answers get a ✓ and the student sees "Correct!" or
    "Not quite"; a plain opinion poll shows just the results.

Picking an option drops {"poll", "choice"} in /run/lab-messages/poll-answers/.
The listener (root) reads who owns the file, so nobody can answer for
someone else, and sends it to the teacher signed and encrypted.

One window per session: the app is single-instance, so running it again with
the same or a new poll file just refreshes the open window.

Testing aids: LAB_POLL_ANSWER_DIR overrides the drop folder; LAB_POLL_APP_ID the
application id; LAB_MESSAGE_TIMEOUT=N closes after N seconds;
LAB_POLL_SELFTEST=N picks option N (-1: none), then prints what the window shows.
"""

import json
import os
import secrets
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

ANSWER_DIR = os.environ.get("LAB_POLL_ANSWER_DIR", "/run/lab-messages/poll-answers")
APP_ID = os.environ.get("LAB_POLL_APP_ID", "com.school.LabPoll")
RESULTS_SECONDS = 180          # the results close on their own after this
LETTERS = "ABCDEF"

CSS = b"""
.poll-question { font-size: 20pt; font-weight: bold; }
.poll-option { font-size: 14pt; padding: 12px 18px; }
.poll-option label { font-size: 14pt; }
.poll-status { font-size: 12pt; }
.poll-bar trough, .poll-bar progress { min-height: 22px; border-radius: 6px; }
.poll-mine { font-weight: bold; }
.poll-verdict { font-size: 18pt; font-weight: bold; }
.poll-right { color: #1f7a4d; }
.poll-wrong { color: #a4471a; }
.poll-correct-bar progress { background-color: #2e9a62; }
"""


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            poll = json.load(handle)
        options = [str(option) for option in poll["options"]][:len(LETTERS)]
        return {
            "id": str(poll["id"]),
            "question": str(poll["question"]),
            "options": options,
            "closed": poll.get("closed") is True,
            "counts": poll.get("counts") if isinstance(poll.get("counts"), list) else [0] * len(options),
            "answered": poll.get("answered") if isinstance(poll.get("answered"), int) else 0,
            "correct": [n for n in poll.get("correct") or [] if isinstance(n, int) and 0 <= n < len(options)],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def drop_answer(poll_id, choice):
    """Write the answer for the listener to pick up. True if it was written."""
    path = os.path.join(ANSWER_DIR, f"{os.getuid()}-{secrets.token_hex(8)}.json")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"poll": poll_id, "choice": choice}, handle)
        return True
    except OSError:
        return False


def choice_file(poll_id):
    """Remembers this student's answer, so the results can mark it even if
    they closed the window and it opened again."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, f"lab-poll-{''.join(c for c in poll_id if c.isalnum() or c == '-')}.choice")


def remembered_choice(poll_id):
    try:
        with open(choice_file(poll_id), "r", encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def remember_choice(poll_id, choice):
    try:
        with open(choice_file(poll_id), "w", encoding="utf-8") as handle:
            handle.write(str(choice))
    except OSError:
        pass


class PollWindow:

    def __init__(self, app, path):
        self.app = app
        self.path = path
        self.poll = load(path)
        self.choice = remembered_choice(self.poll["id"])
        self.shown_closed = False
        self.window = Gtk.ApplicationWindow(application=app, title="Class poll")
        self.window.set_default_size(560, -1)
        self.window.set_deletable(False)
        self.window.connect("close-request", self.on_close_request)
        self.build()
        self.window.present()
        GLib.timeout_add_seconds(1, self.watch)

    # ----- layout -----

    def build(self):
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.box, f"set_margin_{side}")(26)
        heading = Gtk.Label(label=self.poll["question"])
        heading.add_css_class("poll-question")
        heading.set_wrap(True)
        heading.set_justify(Gtk.Justification.CENTER)
        self.box.append(heading)

        self.area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.box.append(self.area)

        self.status = Gtk.Label(label="Pick one answer.")
        self.status.add_css_class("poll-status")
        self.status.set_wrap(True)
        self.box.append(self.status)

        self.verdict = Gtk.Label()
        self.verdict.add_css_class("poll-verdict")
        self.verdict.set_wrap(True)
        self.verdict.set_visible(False)
        self.box.insert_child_after(self.verdict, heading)

        self.close_button = Gtk.Button(label="Close")
        self.close_button.set_halign(Gtk.Align.CENTER)
        self.close_button.connect("clicked", lambda _b: self.window.destroy())
        self.close_button.set_visible(False)
        self.box.append(self.close_button)

        self.window.set_child(self.box)
        if self.poll["closed"]:
            self.show_results()
        else:
            self.show_options()

    def clear_area(self):
        child = self.area.get_first_child()
        while child:
            self.area.remove(child)
            child = self.area.get_first_child()

    def show_options(self):
        self.clear_area()
        self.buttons = []
        group = None
        for index, option in enumerate(self.poll["options"]):
            button = Gtk.ToggleButton(label=f"{LETTERS[index]}.  {option}")
            button.add_css_class("poll-option")
            child = button.get_child()
            if isinstance(child, Gtk.Label):
                child.set_wrap(True)
                child.set_xalign(0)
            if group:
                button.set_group(group)
            group = group or button
            button.connect("toggled", self.on_pick, index)
            self.area.append(button)
            self.buttons.append(button)

    def show_results(self):
        self.shown_closed = True
        self.clear_area()
        counts = self.poll["counts"]
        answered = self.poll["answered"]
        correct = self.poll["correct"]
        total = sum(counts) or 1
        for index, option in enumerate(self.poll["options"]):
            count = counts[index] if index < len(counts) else 0
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            mine = "   ← your answer" if index == self.choice else ""
            tick = "✓ " if index in correct else ""
            label = Gtk.Label(label=f"{tick}{LETTERS[index]}.  {option}   {count} ({round(100 * count / total)}%){mine}")
            label.set_xalign(0)
            label.set_wrap(True)
            if mine:
                label.add_css_class("poll-mine")
            bar = Gtk.ProgressBar()
            bar.add_css_class("poll-bar")
            bar.set_fraction(count / total)
            if index in correct:
                bar.add_css_class("poll-correct-bar")
            row.append(label)
            row.append(bar)
            self.area.append(row)
        self.status.set_text(f"The poll is closed. {answered} answered.")
        if correct:
            answer = " or ".join(LETTERS[index] for index in correct)
            self.verdict.remove_css_class("poll-right")
            self.verdict.remove_css_class("poll-wrong")
            if self.choice in correct:
                self.verdict.set_text("Correct!")
                self.verdict.add_css_class("poll-right")
            elif self.choice is None:
                self.verdict.set_text(f"The answer was {answer}.")
            else:
                self.verdict.set_text(f"Not quite: the answer was {answer}.")
                self.verdict.add_css_class("poll-wrong")
            self.verdict.set_visible(True)
        self.close_button.set_visible(True)
        self.window.set_deletable(True)
        GLib.timeout_add_seconds(RESULTS_SECONDS, lambda: self.window.destroy() or False)

    # ----- events -----

    def on_pick(self, button, index):
        if not button.get_active() or self.shown_closed:
            return
        if drop_answer(self.poll["id"], index):
            self.choice = index
            remember_choice(self.poll["id"], index)
            self.status.set_text(f"Answer sent: {LETTERS[index]}. You can change it until the poll closes.")
            self.close_button.set_visible(True)
            self.window.set_deletable(True)
        else:
            self.status.set_text("Couldn't send your answer. Try again, or tell your teacher.")

    def on_close_request(self, _window):
        # Blocked (True) until the student has answered or the poll is over.
        return self.choice is None and not self.shown_closed

    def watch(self):
        """Every second: has the listener marked the poll closed?"""
        if self.shown_closed:
            return False
        latest = load(self.path)
        if latest and latest["id"] == self.poll["id"] and latest["closed"]:
            self.poll = latest
            self.show_results()
            return False
        return True

    def refresh(self, path):
        """Run again (same or new poll): bring the window up to date."""
        latest = load(path)
        if not latest:
            return
        if latest["id"] != self.poll["id"]:
            self.path, self.poll, self.shown_closed = path, latest, False
            self.choice = remembered_choice(latest["id"])
            self.window.set_deletable(False)
            self.close_button.set_visible(False)
            self.build()
            GLib.timeout_add_seconds(1, self.watch)
        elif latest["closed"] and not self.shown_closed:
            self.poll = latest
            self.show_results()
        self.window.present()


def main():
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
    state = {"window": None}

    def open_poll(path):
        if state["window"] and state["window"].window.get_visible():
            state["window"].refresh(path)
            return
        if not load(path):
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        state["window"] = PollWindow(app, path)
        timeout = os.environ.get("LAB_MESSAGE_TIMEOUT")
        if timeout:
            GLib.timeout_add_seconds(int(timeout), lambda: app.quit() or False)
        if os.environ.get("LAB_POLL_SELFTEST"):
            GLib.timeout_add(600, selftest, state["window"], int(os.environ["LAB_POLL_SELFTEST"]))

    app.connect("open", lambda application, files, _n, _hint: open_poll(files[0].get_path()))
    app.connect("activate", lambda application: None)
    return app.run([sys.argv[0], *sys.argv[1:2]])


def selftest(poll_window, choice):
    """Pick an option, then print what the window shows (for automated tests)."""
    if choice >= 0 and not poll_window.poll["closed"]:
        poll_window.buttons[choice].set_active(True)
    print("STATUS:" + poll_window.status.get_text(), flush=True)
    print("CLOSABLE:" + str(not poll_window.on_close_request(None)), flush=True)

    def after_close():
        if poll_window.shown_closed:
            print("RESULTS:" + poll_window.status.get_text(), flush=True)
            if poll_window.verdict.get_visible():
                print("VERDICT:" + poll_window.verdict.get_text(), flush=True)
            child = poll_window.area.get_first_child()
            while child:
                print("ROW:" + child.get_first_child().get_text(), flush=True)
                child = child.get_next_sibling()
            poll_window.app.quit()
            return False
        return True
    GLib.timeout_add(300, after_close)
    return False


if __name__ == "__main__":
    sys.exit(main())
