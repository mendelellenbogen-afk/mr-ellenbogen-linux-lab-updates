#!/usr/bin/env python3
"""The quiz window (update 0027; 0028: separate first/last name with the
student ID shown, Edit name, "HAND IN" + 5-second countdown, full starter
program + Reset code on Run questions), started in the student's session by
lab-quiz-agent.py:  quiz-window.py <sitting>

First asks for the student's first and last name in two boxes, showing their
student ID (not editable); the quiz can't start without both names, and
"Edit name" goes back to that page (the teacher's requests, 2026-10-18). Then shows this student's own version (/run/lab-quiz/<sitting>/<account>.json),
saves the answers every few seconds to ~/.local/state/lab-quiz/<sitting>.json
(so a crash, reboot or flat battery loses at most a few seconds), and hands in
by dropping {"sitting"} in /run/lab-quiz/submit. The agent writes
/run/lab-quiz/<sitting>/<account>.status: open, handed (student handed in) or
ended (the teacher ended the quiz). The window can't be closed while open.

Run button (only on parts the teacher allowed): the box starts with the whole
program (class, main method, the question's given variables); "Reset code"
puts that back. Run compiles and runs the box as Main.java, 10 s limit.
Hand in: the student types HAND IN, then a big 5-second countdown can still
be cancelled. The lockdown keeps the internet off meanwhile.

Testing aids: LAB_QUIZ_RUN (folder), LAB_QUIZ_APP_ID, LAB_QUIZ_WINDOWED=1 (not
full screen), LAB_QUIZ_COUNTDOWN (seconds, default 5); LAB_QUIZ_SELFTEST='{"first": "Sam",
"last": "Lee", "answers": {"q1.a": "..."}, "reset": "q4.a", "run": "q4.a",
"handin": "HAND IN", "cancel": true}' fills in, presses the buttons, prints what
the window shows as JSON and quits.
"""

import json
import os
import pwd
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

RUN_DIR = os.environ.get("LAB_QUIZ_RUN", "/run/lab-quiz")
APP_ID = os.environ.get("LAB_QUIZ_APP_ID", "com.school.LabQuiz")
SAVE_SECONDS = 3
COUNTDOWN = int(os.environ.get("LAB_QUIZ_COUNTDOWN", "5"))
CONFIRM_WORDS = "HAND IN"
RUN_SECONDS = 10
MAX_OUTPUT = 4000

CSS = b"""
.quiz-title { font-size: 16pt; font-weight: bold; }
.question-title { font-size: 15pt; font-weight: bold; }
.question-text { font-size: 12.5pt; }
.code-block { font-family: monospace; font-size: 11pt; padding: 10px 12px; border-radius: 6px;
              background: alpha(currentColor, 0.07); }
.part-prompt { font-size: 12pt; font-weight: bold; }
.answer-code { font-family: monospace; font-size: 11pt; }
.answer-text { font-size: 12pt; }
.run-output { font-family: monospace; font-size: 10.5pt; }
.saved { opacity: 0.7; }
.done-big { font-size: 22pt; font-weight: bold; }
.countdown { font-size: 120pt; font-weight: bold; }
.student-id { font-family: monospace; font-size: 13pt; }
"""


def account():
    return pwd.getpwuid(os.getuid()).pw_name


def student_id():
    """The ID as typed at account creation (the account's full name for TDSB
    accounts), else the account name."""
    entry = pwd.getpwuid(os.getuid())
    full = entry.pw_gecos.split(",")[0].strip()
    if entry.pw_name.startswith("tdsb-") and full:
        return full
    return entry.pw_name


def save_path(sitting):
    return os.path.join(os.path.expanduser("~"), ".local", "state", "lab-quiz", f"{sitting}.json")


def load_saved(sitting):
    """(answers, first name, last name) saved earlier, e.g. before a crash."""
    try:
        with open(save_path(sitting), encoding="utf-8") as handle:
            saved = json.load(handle)
        answers = {k: v for k, v in saved.get("answers", {}).items() if isinstance(v, str)}
        text = lambda key: saved.get(key) if isinstance(saved.get(key), str) else ""
        return answers, text("first"), text("last")
    except (OSError, ValueError, AttributeError):
        return {}, "", ""


def clean_name(text):
    """One name as typed, tidied; "" if it isn't usable (needs a letter)."""
    name = " ".join(text.split())[:60]
    return name if any(c.isalpha() for c in name) else ""


def save(sitting, version, answers, first, last):
    path = save_path(sitting)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as handle:
        json.dump({"sitting": sitting, "version": version, "first": first, "last": last,
                   "name": f"{first} {last}".strip(), "answers": answers, "saved": int(time.time())}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(path + ".new", path)


def drop_submission(sitting):
    folder = os.path.join(RUN_DIR, "submit")
    path = os.path.join(folder, secrets.token_hex(8) + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"sitting": sitting}, handle)


def read_status(sitting):
    try:
        with open(os.path.join(RUN_DIR, sitting, f"{account()}.status"), encoding="utf-8") as handle:
            return json.load(handle).get("state", "open")
    except (OSError, ValueError):
        return "open"


def run_code(program):
    """Compile and run the student's whole program. Returns the text to show."""
    work = tempfile.mkdtemp(prefix="lab-quiz-run-")
    try:
        with open(os.path.join(work, "Main.java"), "w", encoding="utf-8") as handle:
            handle.write(program)
        process = subprocess.Popen(["java", "-Xmx256m", "-XX:TieredStopAtLevel=1", "Main.java"], cwd=work,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            out, err = process.communicate(timeout=RUN_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            return f"Stopped after {RUN_SECONDS} seconds. Is there an endless loop?"
        if process.returncode != 0 and err:
            lines = [re.sub(r"^Main\.java:\d+: ", "", line) for line in err.splitlines()
                     if "error:" in line or line.strip().startswith("^") or "Exception" in line]
            text = "Problem:\n" + "\n".join(lines[:8] or err.splitlines()[:8])
            return (out + ("\n" if out else "") + text)[:MAX_OUTPUT]
        return (out or "(Your code ran but printed nothing.)")[:MAX_OUTPUT]
    except FileNotFoundError:
        return "Java isn't available on this laptop. Tell your teacher."
    finally:
        shutil.rmtree(work, ignore_errors=True)


class QuizWindow(Gtk.ApplicationWindow):
    def __init__(self, app, quiz, sitting):
        super().__init__(application=app, title=quiz.get("title", "Quiz"), default_width=1100, default_height=760)
        self.quiz, self.sitting = quiz, sitting
        self.answers, self.first, self.last = load_saved(sitting)
        self.starters = {}           # "q4.a" -> starting program (Run questions)
        self.countdown_left = 0
        self.views = {}              # "q1.a" -> TextView
        self.run_outputs = {}
        self.dirty = False
        self.state = "open"
        self.connect("close-request", lambda _w: self.state == "open")
        self.build()
        GLib.timeout_add_seconds(SAVE_SECONDS, self.autosave)
        GLib.timeout_add_seconds(2, self.check_status)
        if os.environ.get("LAB_QUIZ_WINDOWED") != "1":
            self.fullscreen()

    # ---- layout
    def build(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top = Gtk.Box(spacing=12, margin_top=10, margin_bottom=10, margin_start=16, margin_end=16)
        title = Gtk.Label(label=self.quiz.get("title", "Quiz"), xalign=0, hexpand=True)
        title.add_css_class("quiz-title")
        top.append(title)
        self.who = Gtk.Label(label="")
        top.append(self.who)
        self.edit_name_button = Gtk.Button(label="Edit name")
        self.edit_name_button.connect("clicked", lambda _b: self.show_name_page())
        top.append(self.edit_name_button)
        self.saved_label = Gtk.Label(label="")
        self.saved_label.add_css_class("saved")
        top.append(self.saved_label)
        self.hand_in_button = Gtk.Button(label="Hand in")
        self.hand_in_button.add_css_class("suggested-action")
        self.hand_in_button.connect("clicked", self.on_hand_in)
        top.append(self.hand_in_button)
        outer.append(top)
        outer.append(Gtk.Separator())

        self.main_stack = Gtk.Stack(vexpand=True)
        body = Gtk.Box(vexpand=True)
        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar.set_size_request(210, -1)
        self.sidebar.connect("row-selected", self.on_pick)
        body.append(self.sidebar)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.pages = Gtk.Stack(hexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        body.append(self.pages)
        self.side_labels = []
        questions = self.quiz["questions"]
        for number, question in enumerate(questions, 1):
            row_label = Gtk.Label(xalign=0, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
            self.sidebar.append(row_label)
            self.side_labels.append(row_label)
            self.pages.add_named(self.question_page(number, question, len(questions)), f"q{number}")
        self.main_stack.add_named(body, "quiz")
        self.main_stack.add_named(self.name_page(), "name")
        self.main_stack.add_named(self.hand_in_page(), "handin")
        self.main_stack.add_named(self.countdown_page(), "countdown")
        self.done_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.done_label.add_css_class("done-big")
        done = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, valign=Gtk.Align.CENTER,
                       halign=Gtk.Align.CENTER, margin_start=40, margin_end=40)
        done.append(self.done_label)
        self.done_detail = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        done.append(self.done_detail)
        close = Gtk.Button(label="Close", halign=Gtk.Align.CENTER)
        close.connect("clicked", lambda _b: self.get_application().quit())
        done.append(close)
        self.main_stack.add_named(done, "done")
        outer.append(self.main_stack)
        self.set_child(outer)
        self.refresh_sidebar()
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))
        self.show_who()
        if not (self.first and self.last):
            self.show_name_page()
        else:
            self.main_stack.set_visible_child_name("quiz")

    @property
    def name(self):
        return f"{self.first} {self.last}".strip()

    # ---- name page
    def name_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER, margin_start=40, margin_end=40)
        self.name_heading = Gtk.Label(label="Before you start")
        self.name_heading.add_css_class("done-big")
        box.append(self.name_heading)
        grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        grid.attach(Gtk.Label(label="Student ID", xalign=0), 0, 0, 1, 1)
        shown_id = Gtk.Label(label=student_id(), xalign=0, selectable=False)
        shown_id.add_css_class("student-id")
        grid.attach(shown_id, 1, 0, 1, 1)
        self.first_entry = Gtk.Entry(placeholder_text="First name", width_chars=28)
        self.last_entry = Gtk.Entry(placeholder_text="Last name", width_chars=28)
        grid.attach(Gtk.Label(label="First name", xalign=0), 0, 1, 1, 1)
        grid.attach(self.first_entry, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Last name", xalign=0), 0, 2, 1, 1)
        grid.attach(self.last_entry, 1, 2, 1, 1)
        box.append(grid)
        for entry in (self.first_entry, self.last_entry):
            entry.connect("changed", lambda _e: self.start_button.set_sensitive(self.names_ok()))
            entry.connect("activate", lambda _e: self.on_name())
        self.first_entry.set_text(self.first)
        self.last_entry.set_text(self.last)
        self.start_button = Gtk.Button(label="Start the quiz", halign=Gtk.Align.START, sensitive=self.names_ok())
        self.start_button.add_css_class("suggested-action")
        self.start_button.connect("clicked", lambda _b: self.on_name())
        box.append(self.start_button)
        return box

    def names_ok(self):
        return bool(clean_name(self.first_entry.get_text()) and clean_name(self.last_entry.get_text()))

    def show_name_page(self):
        editing = bool(self.first and self.last)
        self.name_heading.set_label("Your name" if editing else "Before you start")
        self.start_button.set_label("Save and go back to the quiz" if editing else "Start the quiz")
        self.first_entry.set_text(self.first)
        self.last_entry.set_text(self.last)
        self.hand_in_button.set_sensitive(False)
        self.edit_name_button.set_sensitive(False)
        self.main_stack.set_visible_child_name("name")
        self.first_entry.grab_focus()

    def on_name(self):
        if not self.names_ok():
            return
        self.first = clean_name(self.first_entry.get_text())
        self.last = clean_name(self.last_entry.get_text())
        self.dirty = True
        self.autosave()
        self.show_who()
        self.back_to_quiz()

    def back_to_quiz(self):
        self.hand_in_button.set_sensitive(True)
        self.edit_name_button.set_sensitive(True)
        self.main_stack.set_visible_child_name("quiz")

    def show_who(self):
        who = f"{self.name} · ID {student_id()}" if self.name else f"ID {student_id()}"
        self.who.set_label(f"{who} · /{self.quiz.get('total', '')}")

    def question_page(self, number, question, count):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                      margin_start=24, margin_end=24)
        heading = Gtk.Label(label=f"Question {number} ({question['marks']} marks)", xalign=0)
        heading.add_css_class("question-title")
        box.append(heading)
        text = Gtk.Label(label=question["text"], xalign=0, wrap=True, selectable=True)
        text.add_css_class("question-text")
        box.append(text)
        if question.get("code"):
            code = Gtk.Label(label=question["code"], xalign=0, selectable=True)
            code.add_css_class("code-block")
            box.append(code)
        for part in question["parts"]:
            key = f"{question['qid']}.{part['pid']}"
            letter = f"{part['pid']}) " if len(question["parts"]) > 1 else ""
            marks = f"{part['marks']} mark{'s' if part['marks'] != 1 else ''}"
            prompt = Gtk.Label(label=f"{letter}{part['prompt']} ({marks})", xalign=0, wrap=True)
            prompt.add_css_class("part-prompt")
            box.append(prompt)
            view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR if part["kind"] == "text" else Gtk.WrapMode.NONE,
                                top_margin=8, bottom_margin=8, left_margin=10, right_margin=10,
                                accepts_tab=part["kind"] != "text")
            view.add_css_class("answer-code" if part["kind"] in ("code", "output") else "answer-text")
            starter = part.get("starter") if part.get("run") else None
            if starter:
                self.starters[key] = starter
            self.answers.setdefault(key, starter or "")
            view.get_buffer().set_text(self.answers[key])
            view.get_buffer().connect("changed", self.on_changed, key)
            if part["kind"] != "text":
                keys = Gtk.EventControllerKey()
                keys.connect("key-pressed", self.on_key, view)
                view.add_controller(keys)
            frame = Gtk.ScrolledWindow(min_content_height=max(3, part.get("lines", 3)) * 26,
                                       hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
            frame.set_child(view)
            frame.add_css_class("frame")
            box.append(frame)
            self.views[key] = view
            if part.get("run") and starter:
                run_row = Gtk.Box(spacing=10)
                run = Gtk.Button(label="▶ Run my code")
                run.connect("clicked", self.on_run, key)
                run_row.append(run)
                reset = Gtk.Button(label="Reset code")
                reset.connect("clicked", self.on_reset, key)
                run_row.append(reset)
                run_row.append(Gtk.Label(label="Write your code inside main. Reset code puts back the starting code.",
                                         xalign=0, wrap=True))
                box.append(run_row)
                output = Gtk.Label(label="", xalign=0, selectable=True, wrap=True)
                output.add_css_class("run-output")
                box.append(output)
                self.run_outputs[key] = output
        nav = Gtk.Box(spacing=10, margin_top=10)
        if number > 1:
            back = Gtk.Button(label="← Previous")
            back.connect("clicked", lambda _b: self.go(number - 2))
            nav.append(back)
        if number < count:
            forward = Gtk.Button(label="Next →")
            forward.connect("clicked", lambda _b: self.go(number))
            nav.append(forward)
        else:
            nav.append(Gtk.Label(label="Last question. Check your answers, then press Hand in at the top."))
        box.append(nav)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(box)
        return scroller

    # ---- answers
    def on_key(self, _controller, keyval, _code, state, view):
        if keyval == Gdk.KEY_Tab and not state & Gdk.ModifierType.SHIFT_MASK:
            view.get_buffer().insert_at_cursor("    ")
            return True
        return False

    def on_changed(self, buffer, key):
        self.answers[key] = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        self.dirty = True
        self.refresh_sidebar()

    def answered(self, question):
        def filled(key):
            text = self.answers.get(key, "")
            return bool(text.strip()) and text != self.starters.get(key)
        return all(filled(f"{question['qid']}.{p['pid']}") for p in question["parts"])

    def refresh_sidebar(self):
        for number, (question, label) in enumerate(zip(self.quiz["questions"], self.side_labels), 1):
            mark = "✓ " if self.answered(question) else "○ "
            label.set_label(f"{mark}Question {number}  ·  {question['marks']} marks")

    def go(self, index):
        self.sidebar.select_row(self.sidebar.get_row_at_index(index))

    def on_pick(self, _list, row):
        if row is not None:
            self.pages.set_visible_child_name(f"q{row.get_index() + 1}")
            self.autosave()

    def autosave(self):
        if self.dirty and self.state == "open":
            try:
                save(self.sitting, self.quiz.get("version"), self.answers, self.first, self.last)
                self.dirty = False
                self.saved_label.set_label("Saved " + time.strftime("%H:%M:%S"))
            except OSError:
                self.saved_label.set_label("Couldn't save! Tell your teacher.")
        return self.state == "open"

    # ---- run
    def on_reset(self, _button, key):
        dialog = Gtk.AlertDialog(message="Reset your code?",
                                 detail="This puts back the starting code. Everything you typed in this box is lost.",
                                 buttons=["Keep my code", "Reset code"], cancel_button=0, default_button=0)

        def answered(dialog, result):
            try:
                if dialog.choose_finish(result) == 1:
                    self.reset_code(key)
            except GLib.Error:
                pass
        dialog.choose(self, None, answered)

    def reset_code(self, key):
        self.views[key].get_buffer().set_text(self.starters[key])
        self.run_outputs[key].set_label("")

    def on_run(self, button, key):
        button.set_sensitive(False)
        self.run_outputs[key].set_label("Running…")
        code = self.answers.get(key, "")

        def work():
            text = run_code(code)
            GLib.idle_add(lambda: (self.run_outputs[key].set_label(text), button.set_sensitive(True), False)[-1])
        threading.Thread(target=work, daemon=True).start()

    # ---- hand in
    # ---- hand in: type HAND IN, then a countdown that can be cancelled
    def hand_in_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER, margin_start=40, margin_end=40)
        heading = Gtk.Label(label="Hand in your quiz?")
        heading.add_css_class("done-big")
        box.append(heading)
        self.hand_in_detail = Gtk.Label(wrap=True, xalign=0)
        box.append(self.hand_in_detail)
        box.append(Gtk.Label(label=f"To hand in, type {CONFIRM_WORDS} in the box.", xalign=0))
        self.confirm_entry = Gtk.Entry(placeholder_text=CONFIRM_WORDS, width_chars=20)
        self.confirm_entry.connect("changed", lambda e: self.confirm_button.set_sensitive(self.confirm_ok()))
        self.confirm_entry.connect("activate", lambda _e: self.start_countdown() if self.confirm_ok() else None)
        box.append(self.confirm_entry)
        buttons = Gtk.Box(spacing=12)
        keep = Gtk.Button(label="Keep working")
        keep.connect("clicked", lambda _b: self.back_to_quiz())
        buttons.append(keep)
        self.confirm_button = Gtk.Button(label="Hand in", sensitive=False)
        self.confirm_button.add_css_class("destructive-action")
        self.confirm_button.connect("clicked", lambda _b: self.start_countdown())
        buttons.append(self.confirm_button)
        box.append(buttons)
        return box

    def countdown_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER)
        box.append(Gtk.Label(label="Handing in your quiz in"))
        self.countdown_label = Gtk.Label(label=str(COUNTDOWN))
        self.countdown_label.add_css_class("countdown")
        box.append(self.countdown_label)
        cancel = Gtk.Button(label="Cancel — keep working", halign=Gtk.Align.CENTER)
        cancel.add_css_class("suggested-action")
        cancel.connect("clicked", lambda _b: self.cancel_countdown())
        box.append(cancel)
        return box

    def confirm_ok(self):
        return " ".join(self.confirm_entry.get_text().upper().split()) == CONFIRM_WORDS

    def on_hand_in(self, _button):
        missing = [str(n) for n, q in enumerate(self.quiz["questions"], 1) if not self.answered(q)]
        self.hand_in_detail.set_label("You can't change your answers after this."
                                      + (f"\nNot answered yet: question {', '.join(missing)}." if missing else ""))
        self.confirm_entry.set_text("")
        self.hand_in_button.set_sensitive(False)
        self.edit_name_button.set_sensitive(False)
        self.main_stack.set_visible_child_name("handin")
        self.confirm_entry.grab_focus()

    def start_countdown(self):
        self.countdown_left = COUNTDOWN
        self.countdown_label.set_label(str(self.countdown_left))
        self.main_stack.set_visible_child_name("countdown")
        GLib.timeout_add_seconds(1, self.tick_countdown)

    def tick_countdown(self):
        if self.main_stack.get_visible_child_name() != "countdown":
            return False                       # cancelled
        self.countdown_left -= 1
        if self.countdown_left > 0:
            self.countdown_label.set_label(str(self.countdown_left))
            return True
        self.countdown_label.set_label("0")
        self.hand_in()
        return False

    def cancel_countdown(self):
        self.countdown_left = 0
        self.back_to_quiz()

    def hand_in(self):
        self.dirty = True
        self.autosave()
        drop_submission(self.sitting)
        self.hand_in_button.set_sensitive(False)
        self.edit_name_button.set_sensitive(False)
        self.saved_label.set_label("Handing in…")

    def check_status(self):
        state = read_status(self.sitting)
        if state != self.state and state in ("handed", "ended"):
            self.state = state
            self.unfullscreen()
            self.done_label.set_label("Handed in ✓" if state == "handed" else "Your teacher ended the quiz")
            self.done_detail.set_label("Your answers are with your teacher. You can close this window."
                                       if state == "handed" else
                                       "Your answers were handed in as they were. You can close this window.")
            self.main_stack.set_visible_child_name("done")
            return False
        return True


class App(Gtk.Application):
    def __init__(self, sitting):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.sitting = sitting
        self.window = None

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        with open(os.path.join(RUN_DIR, self.sitting, f"{account()}.json"), encoding="utf-8") as handle:
            quiz = json.load(handle)
        self.window = QuizWindow(self, quiz, self.sitting)
        self.window.present()
        script = os.environ.get("LAB_QUIZ_SELFTEST")
        if script:
            GLib.timeout_add(300, self.selftest, json.loads(script))

    def selftest(self, script):
        window = self.window
        state = {"waited": 0, "page": window.main_stack.get_visible_child_name()}
        if script.get("first") is not None or script.get("last") is not None:
            window.first_entry.set_text(script.get("first", ""))
            window.last_entry.set_text(script.get("last", ""))
            window.on_name()
        if script.get("edit_name"):
            window.show_name_page()
            state["edit_page"] = window.main_stack.get_visible_child_name()
            state["edit_button"] = window.start_button.get_label()
            window.first_entry.set_text(script["edit_name"][0])
            window.last_entry.set_text(script["edit_name"][1])
            window.on_name()
        for key, text in script.get("answers", {}).items():
            window.views[key].get_buffer().set_text(text)

        def report():
            print(json.dumps({"first_page": state["page"], "page": window.main_stack.get_visible_child_name(),
                              "name": window.name, "first": window.first, "last": window.last,
                              "who": window.who.get_label(), "edit_page": state.get("edit_page"),
                              "edit_button": state.get("edit_button"), "countdown_seen": state.get("countdown"),
                              "confirm_ok": state.get("confirm_ok"), "handin_page": state.get("handin_page"),
                              "cancelled": state.get("cancelled", False), "starters": sorted(window.starters),
                              "answers": {k: window.answers.get(k, "") for k in window.views},"questions": [q["qid"] for q in window.quiz["questions"]],
                              "sidebar": [label.get_label() for label in window.side_labels],
                              "run_buttons": sorted(window.run_outputs),
                              "run_output": {k: v.get_label() for k, v in window.run_outputs.items()},
                              "state": window.state, "saved": window.saved_label.get_label()}), flush=True)
            self.quit()

        def step():
            state["waited"] += 1
            running = any(v.get_label() == "Running…" for v in window.run_outputs.values())
            page = window.main_stack.get_visible_child_name()
            if page == "countdown":
                state["countdown"] = True
                if script.get("cancel") and state["waited"] >= 2:
                    window.cancel_countdown()
                    state["cancelled"] = True
                return True
            waiting_for_agent = (script.get("handin") and state.get("confirm_ok") and not script.get("cancel")
                                 and window.state == "open")
            if (waiting_for_agent or running) and state["waited"] < 80:
                return True
            report()
            return False

        if script.get("reset"):
            window.reset_code(script["reset"])
        if script.get("run"):
            window.on_run(Gtk.Button(), script["run"])
        window.dirty = True
        window.autosave()
        if script.get("handin") is not None:
            window.on_hand_in(None)
            state["handin_page"] = window.main_stack.get_visible_child_name()
            window.confirm_entry.set_text(script["handin"])
            state["confirm_ok"] = window.confirm_ok()
            if state["confirm_ok"]:
                window.start_countdown()
        GLib.timeout_add(500, step)
        return False


def main():
    if len(sys.argv) != 2:
        print("usage: quiz-window.py SITTING", file=sys.stderr)
        return 2
    return App(sys.argv[1]).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
