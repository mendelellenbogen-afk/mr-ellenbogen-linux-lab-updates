#!/usr/bin/env python3
"""The class game window (update 0043, crews from 0044, carnival lobby from 0046): an escape room the class plays together.

Started by lab-game-agent.py in every desktop session while a game is on, or
from the menu ("Class Game"). It shows what the agent keeps in
/run/lab-game/state.json: the story, the timer, the locks, the Clue Wall and
the live feed. A student also sees their code name and clue cards
(/run/lab-game/deal-<uid>.json, readable only by them) and can post on the
wall and try the locks.

Admin (sudo group) sessions get the big-screen view for the projector:
full screen, large text, no cards and nothing to type (Esc leaves full
screen).

What a student does is dropped as a small file in /run/lab-game/actions;
the agent (root) sends it, signed and encrypted, with the account taken
from the file's owner. Whether a guess was right is decided on the
teacher's computer; the window only shows what comes back.

In a crew game (0044, Cipher Heist) the student sees a big badge in their
crew's colour, only their crew's locks, wall, hints and wrong guesses, and
every crew's openings in the feed; the projector shows a crew scoreboard
instead of the locks. A wrong guess freezes the crew's Try buttons.

Lobby rooms (0046) wait for the teacher to form crews, count time played, keep playing
after finishing, and save each student's multiline justifications privately through the agent.

One window per session (single-instance app): running it again brings the
open window to the front.

Testing aids: LAB_GAME_RUN_DIR, LAB_GAME_APP_ID, LAB_GAME_PROJECTOR=1|0,
LAB_GAME_SOUND (the lab-sound command, "" = none), LAB_GAME_SELFTEST="guess:LOCK:TEXT|post:TEXT|explain:LOCK:TEXT|leave"
does those through the window, then (after LAB_GAME_SELFTEST_WAIT ms) prints what it shows and quits.
"""

import grp
import json
import os
import secrets
import shutil
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango   # noqa: E402

RUN_DIR = os.environ.get("LAB_GAME_RUN_DIR", "/run/lab-game")
APP_ID = os.environ.get("LAB_GAME_APP_ID", "com.school.LabGame")
SOUND = os.environ.get("LAB_GAME_SOUND", "/usr/local/bin/lab-sound")
GUESS_GAP = 5
POST_GAP = 6
FEED_SHOWN = 40
NO_GAME_SECONDS = 8

CSS = b"""
.game-root { background: #0e1621; color: #e3ebf3; }
.game-root label { color: #e3ebf3; }
.game-title { font-size: 20pt; font-weight: 800; }
.game-timer { font-size: 30pt; font-weight: 800; font-family: monospace; color: #7fe3c4; }
.game-timer.low { color: #ff8a7a; }
.game-cost { font-size: 11pt; color: #9fb0c2; }
.game-banner { font-size: 18pt; font-weight: 800; padding: 14px; border-radius: 10px; background: #233246; }
.game-banner.win { background: #1d5a3c; }
.game-banner.lose { background: #6b2525; }
.game-heading { font-size: 11pt; font-weight: 800; letter-spacing: 2px; color: #9fb0c2; }
.game-col { background: #142030; border-radius: 12px; padding: 14px; }
.game-me { font-size: 16pt; font-weight: 800; }
.game-card { background: #1c2b3e; border-radius: 10px; padding: 10px 12px; }
.game-card-title { font-weight: 800; color: #f2c66d; }
.game-lock { background: #1c2b3e; border-radius: 10px; padding: 12px 14px; }
.game-lock.open { background: #1d4a35; }
.game-lock.sealed { background: #182230; }
.game-lock-name { font-size: 14pt; font-weight: 800; }
.game-lock-status { font-weight: 800; color: #f2c66d; }
.game-lock.open .game-lock-status { color: #8ff0bd; }
.game-lock.sealed .game-lock-status { color: #7d8ea3; }
.game-post { padding: 6px 2px; border-bottom: 1px solid #22344a; }
.game-feed { font-size: 10pt; color: #b7c5d4; }
.game-feed.open { color: #8ff0bd; font-weight: 800; }
.game-feed.hint { color: #f2c66d; font-weight: 800; }
.game-feed.wrong { color: #f0a8a0; }
.game-note { color: #9fb0c2; }
button { background: #294861; color: #ffffff; border: 1px solid #64839c; }
button:hover { background: #386582; }
textview, textview text { background: #0e1621; color: #e3ebf3; }
entry { background: #0e1621; color: #e3ebf3; border-color: #3a5170; }
.projector .game-title { font-size: 30pt; }
.projector .game-timer { font-size: 54pt; }
.projector .game-lock-name { font-size: 20pt; }
.projector .game-lock-status { font-size: 15pt; }
.projector .game-post label, .projector .game-feed { font-size: 15pt; }
.projector label { font-size: 14pt; }
.game-crew { font-size: 22pt; font-weight: 900; padding: 10px 16px; border-radius: 10px; color: #ffffff; }
.game-crew-note { font-size: 11pt; font-weight: 600; color: #ffffff; }
.game-score { background: #1c2b3e; border-radius: 10px; padding: 10px 14px; }
.game-score-name { font-size: 16pt; font-weight: 900; }
.projector .game-score-name { font-size: 16pt; }
.projector .game-score label { font-size: 10pt; }
"""


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def is_admin():
    try:
        sudo = grp.getgrnam("sudo").gr_gid
    except KeyError:
        return False
    return sudo in os.getgroups() or os.getgid() == sudo


def clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def guess_cost(cost, elapsed):
    if not isinstance(cost, dict):
        return 0
    try:
        minutes = elapsed / 60
        if minutes < cost["free_minutes"]:
            return 0
        steps = int((minutes - cost["free_minutes"]) // cost["every_minutes"])
        return min(cost["start"] + steps * cost["step"], cost["max"])
    except (KeyError, TypeError, ZeroDivisionError):
        return 0


def drop(action):
    """Leave an action for the agent. True if written."""
    path = os.path.join(RUN_DIR, "actions", f"{os.getuid()}-{secrets.token_hex(8)}.json")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(action, handle, ensure_ascii=False)
        return True
    except OSError:
        return False


def play(name):
    if SOUND and shutil.which(SOUND):
        try:
            subprocess.Popen([SOUND, name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def label(text="", css=None, wrap=True, xalign=0.0, selectable=False, chars=None):
    widget = Gtk.Label(label=text)
    widget.set_xalign(xalign)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        # Wrapped text would otherwise ask for its whole length as width and
        # squeeze the locks column.
        widget.set_max_width_chars(chars or 40)
    if css:
        for name in css.split():
            widget.add_css_class(name)
    widget.set_selectable(selectable)
    return widget


def clear(box):
    child = box.get_first_child()
    while child:
        box.remove(child)
        child = box.get_first_child()


def column(title, width=None):
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.add_css_class("game-col")
    if width:
        outer.set_size_request(width, -1)
    outer.append(label(title, "game-heading"))
    return outer


def scrolled(child, vexpand=True):
    window = Gtk.ScrolledWindow()
    window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    window.set_vexpand(vexpand)
    window.set_child(child)
    return window


class GameWindow:

    def __init__(self, app, projector):
        self.app = app
        self.projector = projector
        self.state = None
        self.game = None
        self.deal = None
        self.lock_rows = {}
        self.post_rows = {}
        self.feed_count = -1
        self.sounds_ready = False
        self.counts = {"open": 0, "hints": 0}
        self.result_shown = None
        self.last_post = 0
        self.crew = None                 # crew games: this student's crew id (from the deal)
        self.crew_css = None

        self.window = Gtk.ApplicationWindow(application=app, title="Class Game")
        self.window.set_default_size(1280, 760)
        self.build()
        self.window.present()
        if projector:
            self.window.maximize()
            self.window.fullscreen()
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self.on_key)
            self.window.add_controller(keys)
        else:
            self.window.maximize()
        self.refresh()
        GLib.timeout_add(1000, self.every_second)

    # ----- layout -----

    def build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.add_css_class("game-root")
        if self.projector:
            root.add_css_class("projector")
        for side in ("top", "bottom", "start", "end"):
            getattr(root, f"set_margin_{side}")(0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(inner, f"set_margin_{side}")(16)
        inner.set_vexpand(True)
        root.append(inner)

        header = Gtk.Box(spacing=16)
        self.title = label("Class Game", "game-title")
        self.title.set_hexpand(True)
        header.append(self.title)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.timer = label("--:--", "game-timer", wrap=False, xalign=1.0)
        self.cost = label("", "game-cost", wrap=False, xalign=1.0)
        side.append(self.timer)
        side.append(self.cost)
        header.append(side)
        inner.append(header)

        self.banner = label("", "game-banner", xalign=0.5)
        self.banner.set_visible(False)
        inner.append(self.banner)
        self.leave = Gtk.Button(label="Leave the game")
        self.leave.connect("clicked", self.on_leave)
        self.leave.set_visible(False)
        inner.append(self.leave)
        self.lobby_label = label("", "game-banner")
        inner.append(self.lobby_label)

        self.crew_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.crew_bar.add_css_class("game-crew")
        self.crew_name = label("", "game-crew", wrap=False)
        self.crew_note = label("", "game-crew-note")
        self.crew_bar.append(self.crew_name)
        self.crew_bar.append(self.crew_note)
        self.crew_bar.set_visible(False)
        inner.append(self.crew_bar)

        body = Gtk.Box(spacing=14)
        body.set_vexpand(True)
        inner.append(body)

        if not self.projector:
            me = column("YOU", 300)
            self.me_name = label("Joining the game…", "game-me", chars=22)
            me.append(self.me_name)
            self.me_note = label("Your clue cards will appear here in a moment.", "game-note", chars=30)
            me.append(self.me_note)
            self.cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            me.append(scrolled(self.cards))
            body.append(me)
            self.me_column = me

        middle = column("THE LOCKS")
        middle.set_hexpand(True)
        self.locks_heading = middle.get_first_child()
        self.locks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        story = Gtk.Expander(label="The story")
        story.set_expanded(self.projector)
        self.story = story
        self.intro = label("", "game-note", chars=90)
        story.set_child(self.intro)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        holder.append(story)
        holder.append(self.locks)
        middle.append(scrolled(holder))
        body.append(middle)

        right = column("CLUE WALL", 560 if self.projector else 380)
        self.wall_heading = right.get_first_child()
        self.wall = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.wall_scroll = scrolled(self.wall)
        right.append(self.wall_scroll)
        if not self.projector:
            row = Gtk.Box(spacing=8)
            self.post_entry = Gtk.Entry()
            self.post_entry.set_hexpand(True)
            self.post_entry.set_max_length(200)
            self.post_entry.set_placeholder_text("Share a clue with the class…")
            self.post_entry.connect("activate", self.on_post)
            self.post_button = Gtk.Button(label="Post")
            self.post_button.connect("clicked", self.on_post)
            row.append(self.post_entry)
            row.append(self.post_button)
            right.append(row)
            self.post_note = label("", "game-note")
            right.append(self.post_note)
        right.append(label("LIVE FEED", "game-heading"))
        self.feed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        feed_scroll = scrolled(self.feed, vexpand=False)
        feed_scroll.set_size_request(-1, 260 if self.projector else 200)
        right.append(feed_scroll)
        body.append(right)
        self.right_column = right

        self.window.set_child(root)

    def crews(self):
        return self.state.get("crews") or [] if self.state else []

    def build_locks(self):
        clear(self.locks)
        self.lock_rows = {}
        self.score_rows = {}
        if self.crews() and self.projector:
            # The big screen shows how far each crew is; their locks and walls are their own.
            grid = Gtk.Grid(column_spacing=10, row_spacing=10)
            grid.set_column_homogeneous(True)
            self.locks.append(grid)
            for index, crew in enumerate(self.crews()):
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                box.add_css_class("game-score")
                name = label("", "game-score-name", wrap=False)
                name.set_markup(f"<span foreground=\"{GLib.markup_escape_text(crew['color'] or '#e3ebf3')}\">"
                                f"{GLib.markup_escape_text(crew['name'])}</span>")
                progress = label("", None, chars=90)
                box.append(name)
                box.append(progress)
                grid.attach(box, index % 4, index // 4, 1, 1)
                self.score_rows[crew["id"]] = progress
            return
        for lock in sorted(self.state["locks"], key=lambda l: l.get("bonus", False)):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.add_css_class("game-lock")
            top = Gtk.Box(spacing=10)
            name = label(("BONUS · " if lock.get("bonus") else "") + lock["name"], "game-lock-name", chars=50)
            name.set_hexpand(True)
            status = label("", "game-lock-status", wrap=False, xalign=1.0)
            top.append(name)
            top.append(status)
            box.append(top)
            prompt = label(lock["prompt"], "game-note", chars=90)
            box.append(prompt)
            reveal = label("", None, selectable=True, chars=90)
            reveal.set_visible(False)
            box.append(reveal)
            row = {"box": box, "status": status, "reveal": reveal, "entry": None, "button": None, "note": None}
            if not self.projector:
                line = Gtk.Box(spacing=8)
                entry = Gtk.Entry()
                entry.set_hexpand(True)
                entry.set_max_length(40)
                entry.set_placeholder_text("Type a fraction or decimal" if lock["kind"] == "fraction" else
                                           "Type a code" if lock["kind"] == "number" else "Type a word")
                if lock["kind"] == "number":
                    entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
                button = Gtk.Button(label="Try")
                entry.connect("activate", self.on_guess, lock["id"])
                button.connect("clicked", self.on_guess, lock["id"])
                line.append(entry)
                line.append(button)
                note = label("", "game-note")
                box.append(line)
                box.append(note)
                row.update(entry=entry, button=button, note=note, line=line)
                if lock["kind"] in ("number", "fraction"):
                    allowed = "0123456789" + ("/." if lock["kind"] == "fraction" else "")
                    def filter_entry(widget, allowed=allowed):
                        value = widget.get_text()
                        clean = "".join(c for c in value if c in allowed)
                        if value != clean:
                            widget.set_text(clean)
                    entry.connect("changed", filter_entry)
                if self.state.get("open_ended"):
                    explain = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                    explain.append(label("Explain how your crew solved it", "game-note"))
                    editor = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
                    editor.set_size_request(-1, 90)
                    explain.append(editor)
                    save = Gtk.Button(label="Save")
                    save.connect("clicked", self.on_explain, lock["id"])
                    explain.append(save)
                    saved = label("", "game-note")
                    explain.append(saved)
                    box.append(explain)
                    row.update(explain=explain, editor=editor, save=save, saved=saved, confirmed=None)
            self.locks.append(box)
            self.lock_rows[lock["id"]] = row

    # ----- keeping up with the agent -----

    def refresh(self):
        state = read_json(os.path.join(RUN_DIR, "state.json"))
        if not state or not state.get("game") or not state.get("started"):
            self.state = None
            self.title.set_text("Class Game")
            self.show_banner("No class game is running right now.", "")
            return
        new_game = (state["game"] != self.game or
                    bool(state.get("lobby")) != bool((self.state or {}).get("lobby")) or
                    state.get("crews") != (self.state or {}).get("crews"))
        self.state, self.game = state, state["game"]
        if new_game:
            self.crew = None
            self.deal = None
            self.crew_bar.set_visible(False)
            crews = bool(state.get("crews"))
            self.wall_heading.set_text("YOUR CREW'S WALL" if crews else "CLUE WALL")
            self.locks_heading.set_text("THE CREWS" if crews and self.projector else "THE LOCKS")
            if self.projector:
                self.wall_scroll.set_visible(not crews)
                self.wall_heading.set_visible(not crews)
                self.story.set_expanded(not crews)      # the scoreboard is what the room watches
            elif crews:
                self.post_entry.set_placeholder_text("Share a clue with your crew…")
            self.title.set_text(state.get("title") or "Class Game")
            self.intro.set_text(state.get("intro") or "")
            self.build_locks()
            clear(self.wall)
            self.post_rows = {}
            self.feed_count = -1
            self.sounds_ready = False
            self.result_shown = None
            self.banner.set_visible(False)
        lobby = state.get("lobby", False)
        self.lobby_label.set_visible(lobby)
        self.lobby_label.set_text(("Waiting for your teacher to make the crews…\n" if not self.projector else "") +
                                  f"{state.get('lobby_count', 0)} students have joined")
        self.locks.set_visible(not lobby)
        self.story.set_visible(not (self.projector and state.get("open_ended") and not lobby))
        self.right_column.set_visible(not lobby and not (self.projector and state.get("open_ended")))
        if not self.projector:
            self.me_column.set_visible(not lobby)
        if lobby:
            self.locks_heading.set_text("THE STORY")
            self.story.set_expanded(True)
        self.update_me()
        self.update_locks()
        self.update_wall()
        self.update_feed()
        self.update_me()
        self.update_result()
        self.sound_cues()
        self.update_timer()

    def my_locks(self):
        """The locks as this student's crew sees them (in a crew game), else as they are."""
        if not self.crews():
            return self.state["locks"]
        mine = (self.state.get("crew_locks") or {}).get(self.crew, {})
        return [{**lock, "open": False, "by": None, "reveal": None, **mine.get(lock["id"], {})}
                for lock in self.state["locks"]]

    def opened(self):
        return {lock["id"] for lock in self.my_locks() if lock.get("open")}

    def frozen_for(self):
        """Seconds this student's crew still can't guess."""
        if not self.crews() or not self.crew:
            return 0
        return max(0, int((self.state.get("frozen") or {}).get(self.crew, 0) - time.time()))

    def update_scores(self):
        crew_locks = self.state.get("crew_locks") or {}
        for crew in self.crews():
            row = self.score_rows.get(crew["id"])
            if row is None:
                continue
            mine = crew_locks.get(crew["id"], {})
            marks = [f"{'✔' if mine.get(lock['id'], {}).get('open') else '·'} {lock['name']}" for lock in self.state["locks"]]
            if self.state.get("open_ended"):
                marks = [f"{'⭐' if lock.get('bonus') and mine.get(lock['id'], {}).get('open') else '✔' if mine.get(lock['id'], {}).get('open') else '·'} {lock['name'].removeprefix('The ')}"
                         for lock in self.state["locks"] if mine.get(lock["id"], {}).get("open")]
                if not marks:
                    marks = ["Investigating…"]
                done = self.state.get("done", {}).get(crew["id"])
                if done:
                    marks.insert(0, f"Case solved! #{done['place']}")
                row.set_text((marks[0] + "\n" + "   ".join(marks[1:])) if done else "   ".join(marks))
            else:
                row.set_text("     ".join(marks))

    def update_locks(self):
        if self.score_rows:
            self.update_scores()
            return
        opened = self.opened()
        over = self.state.get("result") is not None
        waiting = self.crews() and not self.crew
        frozen = self.frozen_for()
        for lock in self.my_locks():
            row = self.lock_rows.get(lock["id"])
            if not row:
                continue
            box = row["box"]
            for name in ("open", "sealed"):
                box.remove_css_class(name)
            sealed = not all(r in opened for r in lock.get("requires", []))
            if lock.get("open"):
                box.add_css_class("open")
                row["status"].set_text(f"OPEN · {lock.get('by') or ''}")
                row["reveal"].set_text(lock.get("reveal") or "")
                row["reveal"].set_visible(True)
            elif sealed:
                box.add_css_class("sealed")
                names = [l["name"] for l in self.state["locks"] if l["id"] in lock.get("requires", []) and l["id"] not in opened]
                row["status"].set_text("SEALED")
                row["reveal"].set_text("Opens up after: " + ", ".join(names))
                row["reveal"].set_visible(True)
            else:
                row["status"].set_text("LOCKED")
                row["reveal"].set_visible(False)
            if row.get("explain"):
                row["explain"].set_visible(bool(lock.get("open")))
                row["editor"].set_editable(not over)
                row["save"].set_sensitive(not over)
                saved = (self.deal or {}).get("explanations", {}).get(lock["id"])
                if saved and saved != row["confirmed"]:
                    row["confirmed"] = saved
                    row["editor"].get_buffer().set_text(saved["text"])
                    row["saved"].set_text("Saved ✓ (" + time.strftime("%H:%M", time.localtime(saved["at"])) + ")")
                elif not saved and (self.deal or {}).get("explained", {}).get(lock["id"]):
                    row["saved"].set_text("Saved ✓ (" + time.strftime("%H:%M", time.localtime(self.deal["explained"][lock["id"]])) + ")")
            if row.get("line"):
                row["line"].set_visible(not lock.get("open") and not sealed and not over and not waiting)
                if frozen and row.get("button"):
                    row["entry"].set_sensitive(False)
                    row["button"].set_sensitive(False)
                    row["note"].set_text(f"Your crew is frozen for {frozen} s after a wrong guess.")
                    row["frozen"] = True
                elif row.get("frozen"):
                    row["frozen"] = False
                    row["entry"].set_sensitive(True)
                    row["button"].set_sensitive(True)
                    row["note"].set_text("")

    def update_wall(self):
        at_bottom = self.near_bottom()
        added = False
        for post in self.state.get("posts", []):
            if self.crews() and post.get("crew") != self.crew:
                continue
            n = post["n"]
            if n not in self.post_rows:
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                box.add_css_class("game-post")
                who = label("", None, selectable=False)
                who.set_markup(f"<b><span foreground=\"{GLib.markup_escape_text(post.get('color') or '#9fb0c2')}\">"
                               f"{GLib.markup_escape_text(post.get('who') or '?')}</span></b>")
                box.append(who)
                box.append(label(post.get("text") or "", None, selectable=True))
                self.wall.append(box)
                self.post_rows[n] = box
                added = True
            self.post_rows[n].set_visible(not post.get("hidden"))
        if added and at_bottom:
            GLib.idle_add(self.scroll_down)

    def near_bottom(self):
        adjustment = self.wall_scroll.get_vadjustment()
        return adjustment.get_value() + adjustment.get_page_size() >= adjustment.get_upper() - 40

    def scroll_down(self):
        adjustment = self.wall_scroll.get_vadjustment()
        adjustment.set_value(adjustment.get_upper())
        return False

    def update_feed(self):
        feed = self.state.get("feed", [])
        if len(feed) == self.feed_count and feed:
            return
        self.feed_count = len(feed)
        clear(self.feed)
        if self.crews():
            # Our crew's news, everyone's openings, and what's for the whole class.
            feed = [item for item in feed if not item.get("crew") or item["crew"] == self.crew
                    or item.get("kind") == "open"]
        for item in reversed(feed[-FEED_SHOWN:]):
            line = label(item.get("text", ""), "game-feed")
            if item.get("kind") in ("open", "hint", "wrong"):
                line.add_css_class(item["kind"])
            self.feed.append(line)

    def update_me(self):
        if self.projector:
            return
        deal = read_json(os.path.join(RUN_DIR, f"deal-{os.getuid()}.json"))
        if not deal or deal.get("game") != self.game:
            waited = time.time() - (self.state.get("started") or time.time())
            if self.deal is None and waited > 60:
                self.me_note.set_text("Your cards haven't arrived yet. Keep the window open, or team up with a "
                                      "neighbour and use the Clue Wall.")
            return
        if self.deal == deal:
            return
        self.deal = deal
        if deal.get("crew") and self.crews():
            self.show_crew(deal)
        color = GLib.markup_escape_text(deal.get("color") or "#e3ebf3")
        self.me_name.set_markup(f"<span foreground=\"{color}\">{GLib.markup_escape_text(deal.get('codename') or '')}</span>")
        self.me_note.set_text("Nobody else can see your cards. Share them on the Clue Wall, or out loud.")
        clear(self.cards)
        for card in deal.get("cards", []):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.add_css_class("game-card")
            if card.get("away"):
                box.append(label("Not yours: take it to that crew (or trade it).", "game-note", chars=28))
            box.append(label(card.get("title", ""), "game-card-title", chars=28))
            box.append(label(card.get("text", ""), None, selectable=True, chars=28))
            self.cards.append(box)

    def show_crew(self, deal):
        """The big crew badge, in the crew's colour."""
        color = deal.get("crew_color") or "#53667c"
        if not (len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
            color = "#53667c"
        if self.crew_css is None:
            self.crew_css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.crew_css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.crew_css.load_from_data(f".game-crew {{ background: {color}; }}\n"
                                     f".game-root {{ border: 10px solid {color}; }}".encode())
        self.crew = deal["crew"]
        self.crew_name.set_text(f"YOU'RE IN THE {(deal.get('crew_name') or deal['crew']).upper()}")
        self.crew_note.set_text("Find the other screens in this colour: that's your crew. Your crew's locks and "
                                "wall are only yours.")
        self.crew_bar.set_visible(True)
        self.feed_count = -1
        clear(self.wall)
        self.post_rows = {}

    def update_result(self):
        result = self.state.get("result")
        if self.state.get("open_ended"):
            done = self.state.get("done", {}).get(self.crew)
            self.leave.set_visible(bool(done) and not self.projector)
            if result:
                self.show_banner("Your teacher ended the game.", "")
                if not self.projector:
                    self.post_entry.set_sensitive(False)
                    self.post_button.set_sensitive(False)
            elif done and not self.projector:
                self.show_banner(f"Case solved! Your crew placed #{done['place']}", "win")
            return
        if result == self.result_shown:
            return
        self.result_shown = result
        if result == "won":
            name = self.state.get("winner_name") or "A crew"
            if self.projector:
                self.show_banner(f"{name.upper()} CRACKED THE VAULT AND WINS THE HEIST!", "win")
            elif self.state.get("winner") == self.crew:
                self.show_banner("YOUR CREW CRACKED THE VAULT! You win the heist!", "win")
            else:
                self.show_banner(f"The {name} cracked their vault first. Game over.", "lose")
        elif result == "timeout" and self.crews():
            self.show_banner("TIME'S UP. No crew cracked its vault tonight.", "lose")
        elif result == "escaped":
            self.show_banner(f"YOU ESCAPED!  With {clock(self.state.get('left', 0))} to spare.", "win")
        elif result == "timeout":
            self.show_banner("TIME'S UP. The cleaner swept the memory… better luck next time.", "lose")
        elif result == "ended":
            self.show_banner("Your teacher ended the game.", "")
        if result and not self.projector:
            self.post_entry.set_sensitive(False)
            self.post_button.set_sensitive(False)

    def show_banner(self, text, kind):
        self.banner.set_text(text)
        for name in ("win", "lose"):
            self.banner.remove_css_class(name)
        if kind:
            self.banner.add_css_class(kind)
        self.banner.set_visible(True)

    def sound_cues(self):
        opened = len(self.opened())
        hints = len([h for h in self.state.get("hints", []) if not h.get("crew") or h["crew"] == self.crew])
        result = self.state.get("result")
        if self.sounds_ready:
            if result == "won" and self.counts.get("result") != result:
                play("tada")                       # the whole room hears that someone won
            elif result == "escaped" and self.counts.get("result") != result:
                play("tada")
            elif result == "timeout" and self.counts.get("result") != result:
                play("bell")
            elif opened > self.counts["open"]:
                play("ding")
            elif hints > self.counts["hints"]:
                play("bell")
        self.counts = {"open": opened, "hints": hints, "result": result}
        self.sounds_ready = True

    def update_timer(self):
        if not self.state:
            return
        if self.state.get("result"):
            left = self.state.get("left", 0) if self.state["result"] in ("escaped", "won") else 0
        else:
            left = self.state.get("deadline", 0) - time.time()
        if self.state.get("open_ended"):
            until = self.state.get("ended_at") or time.time()
            left = 0 if self.state.get("lobby") else until - self.state.get("started", until)
        self.timer.set_text(clock(left))
        if left < 120 and not self.state.get("open_ended"):
            self.timer.add_css_class("low")
        else:
            self.timer.remove_css_class("low")
        cost = guess_cost(self.state.get("cost"), time.time() - (self.state.get("started") or time.time()))
        if self.state.get("result") or self.state.get("lobby"):
            self.cost.set_text("")
        elif self.crews():
            frozen = self.frozen_for()
            if frozen:
                self.cost.set_text(f"Your crew is frozen: {frozen} s")
            else:
                self.cost.set_text("Wrong guesses are free for now" if cost == 0
                                   else f"A wrong guess freezes your crew {cost} s")
        else:
            self.cost.set_text("Wrong guesses are free for now" if cost == 0 else f"A wrong guess costs {cost} s")

    def every_second(self):
        state_path = os.path.join(RUN_DIR, "state.json")
        try:
            mtime = os.stat(state_path).st_mtime
        except OSError:
            mtime = None
        if mtime != getattr(self, "seen_mtime", None) or not self.projector:
            self.seen_mtime = mtime
            self.refresh()
        else:
            self.update_timer()
        if self.state and self.crews() and not self.projector:
            self.update_locks()          # the freeze counts down
        if self.state is None and not hasattr(self, "no_game_since"):
            self.no_game_since = time.time()
        if self.state is None and time.time() - self.no_game_since > NO_GAME_SECONDS:
            self.window.destroy()
            return False
        return True

    # ----- what the student does -----

    def on_explain(self, _widget, lock_id):
        if not self.state or self.state.get("result") or lock_id not in self.opened():
            return
        row = self.lock_rows[lock_id]
        buffer = row["editor"].get_buffer()
        value = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        value = value.encode("utf-8")[:1200].decode("utf-8", "ignore")
        if value.strip() and drop({"game": self.game, "type": "explain", "lock": lock_id, "text": value}):
            row["saved"].set_text("Sending…")

    def missing_explanations(self):
        saved = (self.deal or {}).get("explanations", {})
        times = (self.deal or {}).get("explained", {})
        return [lock["name"] for lock in self.my_locks()
                if lock.get("open") and lock["id"] not in saved and lock["id"] not in times]

    def on_leave(self, _widget):
        missing = self.missing_explanations()
        if missing:
            self.leave_prompt = "You haven't written how your crew solved: " + ", ".join(missing) + ". Leave anyway?"
            dialog = Gtk.MessageDialog(transient_for=self.window, modal=True, text=self.leave_prompt)
            self.leave_dialog = dialog
            dialog.add_button("Keep writing", Gtk.ResponseType.CANCEL)
            dialog.add_button("Leave anyway", Gtk.ResponseType.ACCEPT)
            def response(dialog, code):
                dialog.destroy()
                if code == Gtk.ResponseType.ACCEPT:
                    self.window.destroy()
            dialog.connect("response", response)
            dialog.present()
        else:
            self.window.destroy()

    def on_guess(self, _widget, lock_id):
        row = self.lock_rows.get(lock_id)
        if not row or not self.state or self.state.get("result"):
            return
        guess = row["entry"].get_text().strip()
        if not guess:
            return
        if drop({"game": self.game, "type": "guess", "lock": lock_id, "text": guess}):
            row["note"].set_text(f"You tried “{guess}”. Checking…")
            row["entry"].set_text("")
            row["entry"].set_sensitive(False)
            row["button"].set_sensitive(False)

            def again():
                row["entry"].set_sensitive(True)
                row["button"].set_sensitive(True)
                row["note"].set_text("")
                return False
            GLib.timeout_add_seconds(GUESS_GAP, again)
        else:
            row["note"].set_text("Couldn't send that. Try again, or tell your teacher.")

    def on_post(self, _widget):
        if not self.state or self.state.get("result"):
            return
        text = self.post_entry.get_text().strip()
        if not text:
            return
        wait = POST_GAP - (time.time() - self.last_post)
        if wait > 0:
            self.post_note.set_text(f"Wait {int(wait) + 1} s before posting again.")
            return
        if drop({"game": self.game, "type": "post", "text": text}):
            self.last_post = time.time()
            self.post_entry.set_text("")
            self.post_note.set_text("Posted. It shows up on the wall in a moment.")
            GLib.timeout_add_seconds(POST_GAP, lambda: self.post_note.set_text("") or False)
        else:
            self.post_note.set_text("Couldn't post that. Try again, or tell your teacher.")

    def on_key(self, _controller, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            if self.window.is_fullscreen():
                self.window.unfullscreen()
            else:
                self.window.fullscreen()
            return True
        return False


def selftest(game_window, script):
    """Do the scripted actions, then print what the window shows (tests)."""
    for step in [s for s in script.split("|") if s]:
        kind, _, rest = step.partition(":")
        if kind == "guess":
            lock_id, _, guess = rest.partition(":")
            row = game_window.lock_rows[lock_id]
            row["entry"].set_text(guess)
            row["button"].emit("clicked")
        elif kind == "explain":
            lock_id, _, value = rest.partition(":")
            row = game_window.lock_rows[lock_id]
            row["editor"].get_buffer().set_text(value)
            row["save"].emit("clicked")
            print("SENDING:" + row["saved"].get_text(), flush=True)
        elif kind == "leave":
            game_window.leave.emit("clicked")
        elif kind == "post":
            game_window.post_entry.set_text(rest)
            game_window.post_button.emit("clicked")

    def report():
        game_window.refresh()
        out = lambda line: print(line, flush=True)
        out("LOBBY:" + (game_window.lobby_label.get_text() if game_window.lobby_label.get_visible() else ""))
        out("LEAVE:" + str(game_window.leave.get_visible()))
        out("LEAVEPROMPT:" + getattr(game_window, "leave_prompt", ""))
        out("MISSING:" + ", ".join(game_window.missing_explanations()))
        for lock_id, row in game_window.lock_rows.items():
            if row.get("explain"):
                out(f"READONLY:{lock_id}:{not row['editor'].get_editable()}")
                out(f"EXPLAIN:{lock_id}:{row['saved'].get_text()}:{row['explain'].get_visible()}")
        out("TITLE:" + game_window.title.get_text())
        out("TIMER:" + game_window.timer.get_text())
        out("COST:" + game_window.cost.get_text())
        out("BANNER:" + (game_window.banner.get_text() if game_window.banner.get_visible() else ""))
        if game_window.crew_bar.get_visible():
            out("CREW:" + game_window.crew_name.get_text())
        for crew_id, row in getattr(game_window, "score_rows", {}).items():
            out(f"SCORE:{crew_id}:{row.get_text()}")
        if not game_window.projector:
            out("ME:" + game_window.me_name.get_text())
            child = game_window.cards.get_first_child()
            while child:
                title = child.get_first_child()
                if title.get_text().startswith("Not yours"):
                    title = title.get_next_sibling()
                    out("AWAY:" + title.get_text())
                out("CARD:" + title.get_text())
                child = child.get_next_sibling()
        for lock_id, row in game_window.lock_rows.items():
            visible = row.get("line").get_visible() if row.get("line") else False
            out(f"LOCK:{lock_id}:{row['status'].get_text()}:{'input' if visible else 'no-input'}")
        for n, box in sorted(game_window.post_rows.items()):
            if box.get_visible():
                out(f"POST:{box.get_first_child().get_text()}:{box.get_last_child().get_text()}")
        child = game_window.feed.get_first_child()
        while child:
            out("FEED:" + child.get_text())
            child = child.get_next_sibling()
        if not game_window.projector:
            out("POSTNOTE:" + game_window.post_note.get_text())
        game_window.app.quit()
        return False
    GLib.timeout_add(int(os.environ.get("LAB_GAME_SELFTEST_WAIT", "800")), report)
    return False


def main():
    flags = getattr(Gio.ApplicationFlags, "DEFAULT_FLAGS", Gio.ApplicationFlags.FLAGS_NONE)
    app = Gtk.Application(application_id=APP_ID, flags=flags)
    holder = {}

    def activate(application):
        if holder.get("window") and holder["window"].window.get_visible():
            holder["window"].window.present()
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        projector = os.environ.get("LAB_GAME_PROJECTOR")
        projector = is_admin() if projector is None else projector == "1"
        holder["window"] = GameWindow(application, projector)
        if os.environ.get("LAB_GAME_SELFTEST") is not None:
            GLib.timeout_add(700, selftest, holder["window"], os.environ["LAB_GAME_SELFTEST"])

    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
