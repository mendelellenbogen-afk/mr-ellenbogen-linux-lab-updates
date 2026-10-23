#!/usr/bin/env python3
"""The quiz window (update 0027; 0028: separate first/last name with the
student ID shown, Edit name, "HAND IN" + 5-second countdown, full starter
program + Reset code on Run questions; 0030: True/False and multiple choice
answered with buttons, a code snippet per part, question titles, half marks,
and an Input box for Run questions whose program reads the keyboard; 0036:
sounds and the teacher's end countdown), started in the student's session by
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

Choice parts ("kind": "choice", "options": [[value, text], ...]) show one
toggle button per option; the answer is the chosen value ("T", "b"), and
clicking the chosen one again clears it. Run parts with "stdin" get an Input
box: its text is the program's keyboard input (e.g. "2 65").

Sounds (update 0036): only in quizzes whose version says "sounds": true (the
teacher's choice per quiz; real tests stay silent). A tick each second of the
HAND IN countdown and of the teacher's end countdown, and a cheer ("yay", or
"tada" on laptops without it) when the quiz is handed in or ended. Played by
lab-sound at the laptop's current volume.
End countdown (update 0036): when the agent's status has "ends_at", a red bar
under the title counts down the seconds left; at 0 the agent hands in.

Feedback (update 0039; the teacher's request, 2026-10-23, the practice quiz
only for now): when the agent's status after the hand-in says "grading", the
window says it is checking the answers; once it says "feedback", it reads
/run/lab-quiz/<sitting>/<account>.feedback and shows the quiz again, locked,
with each part's marks, what was wrong and the correct answer under the
student's own answer (written answers: "Your teacher marks this"), and the
mark at the top. It stays full screen and can't be closed until the status
says "over" (the teacher ended the quiz).
Update 0040 (the teacher's request, 2026-10-23): "I'm done — close the quiz"
(top right, and on the "Checking your answers" page) asks once, then drops
{"sitting", "done": true} in /run/lab-quiz/submit; the agent ends exam mode
for this student and says "over", and the window closes.

Testing aids: LAB_QUIZ_SOUND (the lab-sound command), LAB_QUIZ_RUN (folder), LAB_QUIZ_APP_ID, LAB_QUIZ_WINDOWED=1 (not
full screen), LAB_QUIZ_COUNTDOWN (seconds, default 5); LAB_QUIZ_SELFTEST='{"first": "Sam",
"last": "Lee", "answers": {"q1.a": "..."}, "reset": "q4.a", "run": "q4.a",
"handin": "HAND IN", "cancel": true, "choose": {"q1.1": "T"}, "input": {"q5.a": "2 65"},
"wait_end": true, "wait_review": true, "wait_over": true, "done": true}' fills in, presses the buttons, (waits for the agent to end the quiz,) prints what
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
DONE_LABEL = "I'm done \u2014 close the quiz"
RUN_SECONDS = 10
SOUND = os.environ.get("LAB_QUIZ_SOUND", "/usr/local/bin/lab-sound")
SOUND_DIR = os.environ.get("LAB_QUIZ_SOUND_DIR", "/usr/local/share/lab-sounds")
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
.ending { font-size: 14pt; font-weight: bold; color: #ffffff; background: #c01c28; padding: 8px 16px; }
.student-id { font-family: monospace; font-size: 13pt; }
.choice { font-size: 12pt; padding: 6px 14px; }
button.choice:checked { background: #1c71d8; color: #ffffff; font-weight: bold; }
.review { font-size: 13pt; font-weight: bold; color: #ffffff; background: #1a5fb4; padding: 8px 16px; }
.feedback { font-size: 11.5pt; padding: 8px 12px; border-radius: 6px; }
.feedback-right { background: alpha(#2ec27e, 0.18); }
.feedback-wrong { background: alpha(#e01b24, 0.15); }
.feedback-teacher { background: alpha(currentColor, 0.07); }
.feedback-code { font-family: monospace; font-size: 10.5pt; }
"""


def marks_text(marks):
    """2 -> "2 marks", 0.5 -> "0.5 marks", 1 -> "1 mark"."""
    number = str(int(marks)) if float(marks).is_integer() else str(marks)
    return f"{number} mark{'' if marks == 1 else 's'}"


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


def drop_done(sitting):
    """Tell the agent this student is done looking at the marks (update 0040)."""
    folder = os.path.join(RUN_DIR, "submit")
    path = os.path.join(folder, secrets.token_hex(8) + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"sitting": sitting, "done": True}, handle)


def read_status(sitting):
    return read_status_full(sitting).get("state", "open")


def read_status_full(sitting):
    """The agent's status: {"state": open|handed|ended, "ends_at": time (0036)}."""
    try:
        with open(os.path.join(RUN_DIR, sitting, f"{account()}.status"), encoding="utf-8") as handle:
            status = json.load(handle)
        return status if isinstance(status, dict) else {}
    except (OSError, ValueError):
        return {}


def number_text(value):
    """2 -> "2", 1.5 -> "1.5"."""
    return str(int(value)) if float(value).is_integer() else str(value)


def load_feedback(sitting):
    """The agent's marks for this student (update 0039), or None."""
    try:
        with open(os.path.join(RUN_DIR, sitting, f"{account()}.feedback"), encoding="utf-8") as handle:
            feedback = json.load(handle)
        return feedback if isinstance(feedback, dict) and isinstance(feedback.get("parts"), dict) else None
    except (OSError, ValueError):
        return None


def cheer_name():
    return "yay" if os.path.exists(os.path.join(SOUND_DIR, "yay.wav")) else "tada"


def run_code(program, keyboard=None):
    """Compile and run the student's whole program, with `keyboard` as its
    input (Scanner) when the question has an Input box. Returns the text to show."""
    work = tempfile.mkdtemp(prefix="lab-quiz-run-")
    try:
        with open(os.path.join(work, "Main.java"), "w", encoding="utf-8") as handle:
            handle.write(program)
        process = subprocess.Popen(["java", "-Xmx256m", "-XX:TieredStopAtLevel=1", "Main.java"], cwd=work,
                                   stdin=subprocess.DEVNULL if keyboard is None else subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            out, err = process.communicate(None if keyboard is None else keyboard.strip() + "\n",
                                           timeout=RUN_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            return f"Stopped after {RUN_SECONDS} seconds. Is there an endless loop?"
        if process.returncode != 0 and err:
            lines = [re.sub(r"^Main\.java:\d+: ", "", line) for line in err.splitlines()
                     if "error:" in line or line.strip().startswith("^") or "Exception" in line]
            text = "Problem:\n" + "\n".join(lines[:8] or err.splitlines()[:8])
            if keyboard is not None and "NoSuchElementException" in err:
                text += "\nYour program wanted more input: type the values in the Input box, then Run."
            elif keyboard is not None and "InputMismatchException" in err:
                text += "\nThe Input box has something that isn't the kind of value your program reads."
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
        self.run_inputs = {}         # "q5.a" -> Entry (Run questions that read the keyboard)
        self.choices = {}            # "q1.1" -> {value: ToggleButton}
        self.dirty = False
        self.state = "open"
        self.sounds = quiz.get("sounds") is True      # update 0036: only quizzes the teacher marked
        self.played = []                             # sound names, for the self-test
        self.ends_at = None                          # the teacher's end countdown (0036)
        self.reviewing = False                       # update 0039: handed in, marks coming or shown
        self.review = None                           # the marks, once shown
        self.over = False                            # the teacher ended the quiz: may close
        self.feedback_boxes = {}                     # "q1.a" -> (box, text label, code label)
        self.leaving = False                         # 0040: pressed "I'm done", waiting for the agent
        self.left = False                            # self-test: would have closed
        self.locked_rows = []                        # choice rows and Run/Reset/Input, locked in review
        self.connect("close-request", lambda _w: self.state == "open" or (self.reviewing and not self.over))
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
        self.close_button = Gtk.Button(label="Close", visible=False)
        self.close_button.connect("clicked", self.on_close)
        top.append(self.close_button)
        outer.append(top)
        self.ending_label = Gtk.Label(label="", xalign=0, visible=False)
        self.ending_label.add_css_class("ending")
        outer.append(self.ending_label)
        self.review_label = Gtk.Label(label="", xalign=0, wrap=True, visible=False)
        self.review_label.add_css_class("review")
        outer.append(self.review_label)
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
            row_label = Gtk.Label(xalign=0, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
                                  wrap=True)
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
        close.connect("clicked", self.on_close)
        done.append(close)
        self.done_close = close
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
        total = self.quiz.get("total", "")
        total = str(int(total)) if isinstance(total, (int, float)) and float(total).is_integer() else total
        self.who.set_label(f"{who} · /{total}")

    def question_page(self, number, question, count):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                      margin_start=24, margin_end=24)
        name = question.get("title") or f"Question {number}"
        heading = Gtk.Label(label=f"{name} ({marks_text(question['marks'])})", xalign=0, wrap=True)
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
            prompt = Gtk.Label(label=f"{letter}{part['prompt']} ({marks_text(part['marks'])})", xalign=0, wrap=True,
                               selectable=True)
            prompt.add_css_class("part-prompt")
            box.append(prompt)
            if part.get("code"):
                snippet = Gtk.Label(label=part["code"], xalign=0, selectable=True)
                snippet.add_css_class("code-block")
                box.append(snippet)
            if part["kind"] == "choice":
                row = self.choice_row(key, part)
                self.locked_rows.append(row)
                box.append(row)
                self.feedback_box(box, key)
                continue
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
                if part.get("stdin"):
                    input_row = Gtk.Box(spacing=10)
                    input_row.append(Gtk.Label(label="Input:"))
                    entry = Gtk.Entry(placeholder_text="the values your program reads, e.g. 2 65", width_chars=34)
                    input_row.append(entry)
                    input_row.append(Gtk.Label(label="(typed in for your program when you press Run)", xalign=0,
                                               wrap=True))
                    box.append(input_row)
                    self.locked_rows.append(input_row)
                    self.run_inputs[key] = entry
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
                self.locked_rows.append(run_row)
                output = Gtk.Label(label="", xalign=0, selectable=True, wrap=True)
                output.add_css_class("run-output")
                box.append(output)
                self.run_outputs[key] = output
            self.feedback_box(box, key)
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

    def feedback_box(self, box, key):
        """Where the marks for this part appear after the hand-in (0039)."""
        feedback = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False)
        feedback.add_css_class("feedback")
        text = Gtk.Label(xalign=0, wrap=True, selectable=True)
        feedback.append(text)
        code = Gtk.Label(xalign=0, selectable=True, visible=False)
        code.add_css_class("feedback-code")
        feedback.append(code)
        box.append(feedback)
        self.feedback_boxes[key] = (feedback, text, code)

    def choice_row(self, key, part):
        """One toggle button per option; at most one is pressed."""
        options = part.get("options") or []
        many = len(options) > 2
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if many else Gtk.Orientation.HORIZONTAL,
                      spacing=6 if many else 12, margin_start=6)
        buttons = {}
        self.answers.setdefault(key, "")
        for value, text in options:
            label = Gtk.Label(label=f"{value})  {text}" if many else text, xalign=0, wrap=True)
            button = Gtk.ToggleButton(halign=Gtk.Align.START if many else Gtk.Align.FILL)
            button.set_child(label)
            button.add_css_class("choice")
            button.set_active(self.answers.get(key) == value)
            button.connect("toggled", self.on_choice, key, value)
            buttons[value] = button
            row.append(button)
        self.choices[key] = buttons
        return row

    def on_choice(self, button, key, value):
        if getattr(self, "_choosing", False):
            return
        self._choosing = True
        try:
            if button.get_active():
                for other, other_button in self.choices[key].items():
                    if other != value:
                        other_button.set_active(False)
                self.answers[key] = value
            elif self.answers.get(key) == value:
                self.answers[key] = ""
        finally:
            self._choosing = False
        self.dirty = True
        self.refresh_sidebar()

    def choose(self, key, value):
        """Testing aid: press an option's button like a student."""
        button = self.choices[key][value]
        button.set_active(not button.get_active())

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
            name = question.get("title") or f"Question {number}"
            if self.review is not None:
                label.set_label(self.review_side_text(question, name))
                continue
            mark = "✓ " if self.answered(question) else "○ "
            label.set_label(f"{mark}{name}  ·  {marks_text(question['marks'])}")

    def review_side_text(self, question, name):
        results = [self.review["parts"].get(f"{question['qid']}.{p['pid']}") or {} for p in question["parts"]]
        if any(r.get("earned") is None for r in results):
            return f"✎ {name}  ·  teacher marks"
        got = sum(r.get("earned", 0) for r in results)
        mark = "✓" if got == question["marks"] else "✗" if got == 0 else "◐"
        return f"{mark} {name}  ·  {number_text(got)}/{number_text(question['marks'])}"

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
        keyboard = self.run_inputs[key].get_text() if key in self.run_inputs else None

        def work():
            text = run_code(code, keyboard)
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

    def play(self, name):
        """Play a lab sound (0036) if this quiz has sounds; never blocks or fails the quiz."""
        if not self.sounds:
            return
        self.played.append(name)
        try:
            subprocess.Popen([SOUND, name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    def start_countdown(self):
        self.countdown_left = COUNTDOWN
        self.countdown_label.set_label(str(self.countdown_left))
        self.main_stack.set_visible_child_name("countdown")
        self.play("tick")
        GLib.timeout_add_seconds(1, self.tick_countdown)

    def tick_countdown(self):
        if self.main_stack.get_visible_child_name() != "countdown":
            return False                       # cancelled
        self.countdown_left -= 1
        if self.countdown_left > 0:
            self.countdown_label.set_label(str(self.countdown_left))
            self.play("tick")
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
        status = read_status_full(self.sitting)
        state = status.get("state", "open")
        if self.reviewing:
            return self.check_review(status)
        ends_at = status.get("ends_at")
        if state == "open" and isinstance(ends_at, (int, float)) and not self.ends_at:
            self.ends_at = ends_at                   # the teacher started the end countdown
            self.tick_ending()
            GLib.timeout_add_seconds(1, self.tick_ending)
        if state != self.state and state in ("handed", "ended"):
            self.state = state
            self.ending_label.set_visible(False)
            self.play(cheer_name())
            if status.get("grading") or status.get("feedback"):
                self.reviewing = True               # update 0039: marks come, stay in exam mode
                self.hand_in_button.set_visible(False)
                self.edit_name_button.set_visible(False)
                self.saved_label.set_label("")
                self.done_label.set_label("Handed in ✓")
                self.done_detail.set_label("Checking your answers… Your marks appear here in a few seconds.")
                self.done_close.set_label(DONE_LABEL)            # 0040: may leave without waiting
                self.done_close.set_visible(True)
                self.main_stack.set_visible_child_name("done")
                return self.check_review(status)
            self.unfullscreen()
            self.done_label.set_label("Handed in ✓" if state == "handed" else "Your teacher ended the quiz")
            self.done_detail.set_label("Your answers are with your teacher. You can close this window."
                                       if state == "handed" else
                                       "Your answers were handed in as they were. You can close this window.")
            self.main_stack.set_visible_child_name("done")
            return False
        return True


    # ---- feedback after the hand-in (update 0039)
    def on_close(self, _button):
        """Close (once over), or "I'm done" while looking at the marks (0040)."""
        if self.reviewing and not self.over:
            dialog = Gtk.AlertDialog(message="Close the quiz?",
                                     detail="You can't open your marks again after this.",
                                     buttons=["Keep looking", "Close the quiz"], cancel_button=0, default_button=0)

            def answered(dialog, result):
                try:
                    if dialog.choose_finish(result) == 1:
                        self.leave()
                except GLib.Error:
                    pass
            dialog.choose(self, None, answered)
            return
        self.get_application().quit()

    def leave(self):
        if self.leaving:
            return
        self.leaving = True
        try:
            drop_done(self.sitting)
        except OSError:
            self.leaving = False
            return
        for button in (self.close_button, self.done_close):
            button.set_label("Closing…")
            button.set_sensitive(False)

    def check_review(self, status):
        if status.get("feedback") and self.review is None:
            feedback = load_feedback(self.sitting)
            if feedback:
                self.show_review(feedback)
        if status.get("over") and not self.over:
            self.over = True
            if self.leaving:                         # 0040: the student pressed "I'm done"
                if os.environ.get("LAB_QUIZ_SELFTEST"):
                    self.left = True
                else:
                    self.get_application().quit()
                return False
            self.unfullscreen()
            for button in (self.close_button, self.done_close):
                button.set_label("Close")
                button.set_visible(True)
            if self.review is not None:
                self.review_label.set_label(self.review_label.get_label().split("\n")[0]
                                            + "\nYour teacher ended the quiz. You can close this window.")
            else:
                self.done_detail.set_label("Your teacher ended the quiz. You can close this window.")
        return not (self.over and self.review is not None)

    def show_review(self, feedback):
        self.review = feedback
        for view in self.views.values():
            view.set_editable(False)
            view.set_cursor_visible(False)
        for row in self.locked_rows:
            row.set_can_target(False)
            row.set_opacity(0.85)
        for key, (box, text, code) in self.feedback_boxes.items():
            result = feedback["parts"].get(key)
            if not result:
                continue
            marks, earned = result.get("marks", 0), result.get("earned")
            for name in ("feedback-right", "feedback-wrong", "feedback-teacher"):
                box.remove_css_class(name)
            if earned is None:
                box.add_css_class("feedback-teacher")
                text.set_label(f"✎ {result.get('summary', 'Your teacher marks this.')}")
            else:
                right = earned == marks
                box.add_css_class("feedback-right" if right else "feedback-wrong")
                lines = [f"{'✓' if right else '✗'} {number_text(earned)}/{number_text(marks)} "
                         f"mark{'' if marks == 1 else 's'}  ·  {result.get('summary', '')}"]
                lines += [f"   {line}" for line in result.get("details", [])]
                if result.get("correct") is not None and not right:
                    correct = str(result["correct"])
                    if "\n" in correct.strip() or len(correct) > 60:
                        lines.append("A correct answer:")
                        code.set_label(correct.rstrip())
                        code.set_visible(True)
                    else:
                        lines.append(f"Correct answer: {correct}")
                text.set_label("\n".join(lines))
            box.set_visible(True)
        earned, out_of, teacher = feedback.get("earned", 0), feedback.get("out_of", 0), feedback.get("teacher_marks", 0)
        banner = f"Handed in ✓   Your mark: {number_text(earned)} / {number_text(out_of)}"
        if teacher:
            banner += f"   (+ {number_text(teacher)} marked by your teacher)"
        self.review_label.set_label(banner + "\nLook at the feedback under each answer. "
                                    f"When you're done, press \u201c{DONE_LABEL}\u201d at the top.")
        self.review_label.set_visible(True)
        if not self.over and not self.leaving:
            self.close_button.set_label(DONE_LABEL)
            self.close_button.set_visible(True)
        self.refresh_sidebar()
        self.main_stack.set_visible_child_name("quiz")
        self.go(0)

    def tick_ending(self):
        """The red bar: seconds left until the teacher's countdown hands the quiz in."""
        if self.state != "open":
            return False
        left = max(0, int(round(self.ends_at - time.time())))
        self.ending_label.set_label(f"Your teacher is ending the quiz: {left} second{'s' if left != 1 else ''} left. "
                                    "Your answers will be handed in as they are." if left else
                                    "Time's up! Handing in your answers…")
        self.ending_label.set_visible(True)
        if left:
            self.play("tick")
        return left > 0


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
        for key, value in script.get("choose", {}).items():
            for one in value if isinstance(value, list) else [value]:
                window.choose(key, one)
        for key, text in script.get("input", {}).items():
            window.run_inputs[key].set_text(text)

        def report():
            print(json.dumps({"first_page": state["page"], "page": window.main_stack.get_visible_child_name(),
                              "name": window.name, "first": window.first, "last": window.last,
                              "who": window.who.get_label(), "edit_page": state.get("edit_page"),
                              "edit_button": state.get("edit_button"), "countdown_seen": state.get("countdown"),
                              "confirm_ok": state.get("confirm_ok"), "handin_page": state.get("handin_page"),
                              "cancelled": state.get("cancelled", False), "starters": sorted(window.starters),
                              "answers": {k: window.answers.get(k, "") for k in list(window.views) + list(window.choices)},
                              "pressed": {k: [v for v, b in buttons.items() if b.get_active()]
                                          for k, buttons in window.choices.items()},
                              "inputs": sorted(window.run_inputs),"questions": [q["qid"] for q in window.quiz["questions"]],
                              "sidebar": [label.get_label() for label in window.side_labels],
                              "run_buttons": sorted(window.run_outputs),
                              "run_output": {k: v.get_label() for k, v in window.run_outputs.items()},
                              "state": window.state, "saved": window.saved_label.get_label(),
                              "played": window.played, "ending": state.get("ending", ""),
                              "reviewing": window.reviewing, "over": window.over,
                              "review": window.review_label.get_label() if window.review is not None else None,
                              "done": [window.done_label.get_label(), window.done_detail.get_label()],
                              "feedback": {k: [t.get_label(), c.get_label() if c.get_visible() else None]
                                           for k, (b, t, c) in window.feedback_boxes.items() if b.get_visible()},
                              "editable": [k for k, v in window.views.items() if v.get_editable()],
                              "close_visible": window.close_button.get_visible(),
                              "close_label": window.close_button.get_label(),
                              "done_close": [window.done_close.get_visible(), window.done_close.get_label()],
                              "leaving": window.leaving, "left": window.left}), flush=True)
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
            if window.ending_label.get_visible():
                state.setdefault("ending", window.ending_label.get_label())   # the first text shown
            waiting_for_agent = ((script.get("handin") and state.get("confirm_ok") and not script.get("cancel")
                                  or script.get("wait_end")) and window.state == "open"
                                 or script.get("wait_review") and window.review is None and not window.over
                                 or script.get("wait_over") and not window.over
                                 or script.get("done") and not window.left)
            if script.get("done") and window.review is not None and not window.leaving:
                window.leave()
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
