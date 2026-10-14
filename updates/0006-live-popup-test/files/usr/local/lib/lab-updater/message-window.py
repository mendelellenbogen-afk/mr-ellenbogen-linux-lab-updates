#!/usr/bin/env python3
# A simple message window, shown on a user's desktop by show-message.
# Usage: message-window.py TITLE TEXT
# (LAB_MESSAGE_TIMEOUT=N closes it after N seconds; used for testing.)

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

title = sys.argv[1] if len(sys.argv) > 1 else "Message"
text = sys.argv[2] if len(sys.argv) > 2 else ""


def activate(app):
    window = Gtk.ApplicationWindow(application=app, title=title)
    window.set_default_size(460, 220)
    window.set_resizable(False)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    box.set_margin_top(28)
    box.set_margin_bottom(28)
    box.set_margin_start(32)
    box.set_margin_end(32)

    heading = Gtk.Label()
    heading.set_markup(f"<span size='x-large' weight='bold'>{GLib.markup_escape_text(title)}</span>")
    heading.set_wrap(True)
    box.append(heading)

    if text:
        body = Gtk.Label(label=text)
        body.set_wrap(True)
        body.set_justify(Gtk.Justification.CENTER)
        box.append(body)

    button = Gtk.Button(label="OK")
    button.set_halign(Gtk.Align.CENTER)
    button.connect("clicked", lambda _button: window.close())
    box.append(button)

    window.set_child(box)
    window.present()

    timeout = os.environ.get("LAB_MESSAGE_TIMEOUT")
    if timeout:
        GLib.timeout_add_seconds(int(timeout), lambda: window.close() or False)


app = Gtk.Application(
    application_id="com.school.LabMessage",
    flags=Gio.ApplicationFlags.NON_UNIQUE,
)
app.connect("activate", activate)
sys.exit(app.run([]))
