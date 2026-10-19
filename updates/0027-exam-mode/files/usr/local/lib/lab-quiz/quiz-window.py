#!/usr/bin/env python3
"""The quiz window (update 0027), started in the student's session by
lab-quiz-agent.py:  quiz-window.py <sitting>

First asks for the student's first and last name (the teacher's request,
2026-10-18; the quiz can't start without it). Then shows this student's own version (/run/lab-quiz/<sitting>/<account>.json),
saves the answers every few seconds to ~/.local/state/lab-quiz/<sitting>.json
(so a crash, reboot or flat battery loses at most a few seconds), and hands in
by dropping {"sitting"} in /run/lab-quiz/submit. The agent writes
/run/lab-quiz/<sitting>/<account>.status: open, handed (student handed in) or
ended (the teacher ended the quiz). The window can't be closed while open.

Run button (only on parts the teacher allowed): the student's code goes into
the part's run_wrapper (the question's given variables) and runs with
`java Main.java`, 10 s limit. The lockdown keeps the internet off meanwhile.

Testing aids: LAB_QUIZ_RUN (folder), LAB_QUIZ_APP_ID, LAB_QUIZ_WINDOWED=1 (not
full screen), LAB_QUIZ_SELFTEST='{"answers": {"q1.a": "..."}, "run": "q4.a",
"handin": true}' fills in answers, presses Run / Hand in, prints what the
window shows as JSON and quits.
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
"""


def account():
    return pwd.getpwuid(os.getuid()).pw_name


def save_path(sitting):
    return os.path.join(os.path.expanduser("~"), ".local", "state", "lab-quiz", f"{sitting}.json")


def load_saved(sitting):
    """(answers, name) saved earlier, e.g. before a crash."""
    try:
        with open(save_path(sitting), encoding="utf-8") as handle:
            saved = json.load(handle)
        answers = {k: v for k, v in saved.get("answers", {}).items() if isinstance(v, str)}
        name = saved.get("name") if isinstance(saved.get("name"), str) else ""
        return answers, name
    except (OSError, ValueError, AttributeError):
        return {}, ""


def clean_name(text):
    """The name as typed, tidied; "" if it isn't a usable name."""
    name = " ".join(text.split())[:100]
    return name if sum(c.isalpha() for c in name) >= 2 else ""


def save(sitting, version, answers, name):
    path = save_path(sitting)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as handle:
        json.dump({"sitting": sitting, "version": version, "name": name, "answers": answers,
                   "saved": int(time.time())}, handle)
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


def clean_for_run(code, wrapper):
    """Drop re-declarations of the variables the wrapper already declares
    (students often copy `int age = 30;`); keep `int price = 0;` as `price = 0;`."""
    given = re.findall(r"^\s*(?:int|double|boolean|String)\s+(\w+)\s*=", wrapper, re.M)
    declared = re.findall(r"^\s*(?:int|double|boolean|String)\s+(\w+)\s*;", wrapper, re.M)
    for name in given:
        code = re.sub(rf"\b(?:int|double|boolean|String|var)\s+{name}\s*(?:=[^;]*)?;", "", code)
    for name in declared:
        code = re.sub(rf"\b(?:int|double|boolean|String|var)\s+{name}\s*;", "", code)
        code = re.sub(rf"\b(?:int|double|boolean|String|var)\s+{name}\s*=", f"{name} =", code)
    return code


def run_code(code, wrapper):
    """Run the student's code inside the wrapper. Returns the text to show."""
    work = tempfile.mkdtemp(prefix="lab-quiz-run-")
    try:
        with open(os.path.join(work, "Main.java"), "w", encoding="utf-8") as handle:
            handle.write(wrapper.replace("%CODE%", clean_for_run(code, wrapper)))
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
        self.answers, self.name = load_saved(sitting)
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
        if not self.name:
            self.main_stack.set_visible_child_name("name")
            self.hand_in_button.set_sensitive(False)
            self.name_entry.grab_focus()
        else:
            self.main_stack.set_visible_child_name("quiz")

    def name_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER, margin_start=40, margin_end=40)
        heading = Gtk.Label(label="Before you start")
        heading.add_css_class("done-big")
        box.append(heading)
        box.append(Gtk.Label(label="Type your first and last name.", xalign=0))
        self.name_entry = Gtk.Entry(placeholder_text="First and last name", width_chars=36)
        self.name_entry.connect("activate", lambda _e: self.on_name())
        self.name_entry.connect("changed", lambda e: self.start_button.set_sensitive(bool(clean_name(e.get_text()))))
        box.append(self.name_entry)
        self.start_button = Gtk.Button(label="Start the quiz", halign=Gtk.Align.START, sensitive=False)
        self.start_button.add_css_class("suggested-action")
        self.start_button.connect("clicked", lambda _b: self.on_name())
        box.append(self.start_button)
        return box

    def on_name(self):
        name = clean_name(self.name_entry.get_text())
        if not name:
            return
        self.name = name
        self.dirty = True
        self.autosave()
        self.show_who()
        self.hand_in_button.set_sensitive(True)
        self.main_stack.set_visible_child_name("quiz")

    def show_who(self):
        account_name = self.quiz.get("account", account())
        who = f"{self.name} ({account_name})" if self.name else account_name
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
            view.get_buffer().set_text(self.answers.get(key, ""))
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
            if part.get("run") and part.get("run_wrapper"):
                run_row = Gtk.Box(spacing=10)
                run = Gtk.Button(label="▶ Run my code")
                run.connect("clicked", self.on_run, key, part["run_wrapper"])
                run_row.append(run)
                run_row.append(Gtk.Label(label="Runs your code with the values given in the question.", xalign=0))
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
        return all(self.answers.get(f"{question['qid']}.{p['pid']}", "").strip() for p in question["parts"])

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
                save(self.sitting, self.quiz.get("version"), self.answers, self.name)
                self.dirty = False
                self.saved_label.set_label("Saved " + time.strftime("%H:%M:%S"))
            except OSError:
                self.saved_label.set_label("Couldn't save! Tell your teacher.")
        return self.state == "open"

    # ---- run
    def on_run(self, button, key, wrapper):
        button.set_sensitive(False)
        self.run_outputs[key].set_label("Running…")
        code = self.answers.get(key, "")

        def work():
            text = run_code(code, wrapper)
            GLib.idle_add(lambda: (self.run_outputs[key].set_label(text), button.set_sensitive(True), False)[-1])
        threading.Thread(target=work, daemon=True).start()

    # ---- hand in
    def on_hand_in(self, _button):
        missing = [str(n) for n, q in enumerate(self.quiz["questions"], 1) if not self.answered(q)]
        detail = ("You can't change your answers after this."
                  + (f" Not answered yet: question {', '.join(missing)}." if missing else ""))
        dialog = Gtk.AlertDialog(message="Hand in your quiz?", detail=detail,
                                 buttons=["Keep working", "Hand in"], cancel_button=0, default_button=0)

        def answered(dialog, result):
            try:
                if dialog.choose_finish(result) == 1:
                    self.hand_in()
            except GLib.Error:
                pass
        dialog.choose(self, None, answered)

    def hand_in(self):
        self.dirty = True
        self.autosave()
        drop_submission(self.sitting)
        self.hand_in_button.set_sensitive(False)
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
        if script.get("name") is not None:
            window.name_entry.set_text(script["name"])
            window.on_name()
        for key, text in script.get("answers", {}).items():
            window.views[key].get_buffer().set_text(text)

        def report():
            print(json.dumps({"first_page": state["page"], "page": window.main_stack.get_visible_child_name(),
                              "name": window.name, "who": window.who.get_label(),"questions": [q["qid"] for q in window.quiz["questions"]],
                              "sidebar": [label.get_label() for label in window.side_labels],
                              "run_buttons": sorted(window.run_outputs),
                              "run_output": {k: v.get_label() for k, v in window.run_outputs.items()},
                              "state": window.state, "saved": window.saved_label.get_label()}), flush=True)
            self.quit()

        def step():
            state["waited"] += 1
            running = any(v.get_label() == "Running…" for v in window.run_outputs.values())
            if script.get("handin") and window.state == "open" and state["waited"] < 60:
                return True
            if running and state["waited"] < 60:
                return True
            report()
            return False

        if script.get("run"):
            window.on_run(Gtk.Button(), script["run"], [p for q in window.quiz["questions"] for p in q["parts"]
                                                        if f"{q['qid']}.{p['pid']}" == script["run"]][0]["run_wrapper"])
        window.dirty = True
        window.autosave()
        if script.get("handin"):
            window.hand_in()
        GLib.timeout_add(500, step)
        return False


def main():
    if len(sys.argv) != 2:
        print("usage: quiz-window.py SITTING", file=sys.stderr)
        return 2
    return App(sys.argv[1]).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
