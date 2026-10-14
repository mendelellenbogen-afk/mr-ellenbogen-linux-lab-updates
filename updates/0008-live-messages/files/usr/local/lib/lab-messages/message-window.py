#!/usr/bin/env python3
"""Live message pop-up: a title, optional text, and an optional read-only code
box with a Copy button (for code snippets the teacher sends to the class).

Usage: message-window.py MESSAGE.json    ({"title": ..., "text": ..., "code": ...})

Testing aids: LAB_MESSAGE_TIMEOUT=N closes the window after N seconds;
LAB_MESSAGE_SELFTEST=1 presses Copy, prints what landed on the clipboard, exits.
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

CSS = b"""
.lab-code {
    font-family: monospace;
    font-size: 11pt;
    padding: 10px;
    border-radius: 8px;
}
"""


def load_message(path):
    with open(path, "r", encoding="utf-8") as message_file:
        message = json.load(message_file)
    return (
        str(message.get("title") or "Message"),
        str(message.get("text") or ""),
        str(message.get("code") or ""),
    )


def activate(app, title, text, code):
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    window = Gtk.ApplicationWindow(application=app, title=title)
    window.set_default_size(620 if code else 460, -1)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(28)
    box.set_margin_end(28)

    heading = Gtk.Label()
    heading.set_markup(f"<span size='x-large' weight='bold'>{GLib.markup_escape_text(title)}</span>")
    heading.set_wrap(True)
    box.append(heading)

    if text:
        body = Gtk.Label(label=text)
        body.set_wrap(True)
        body.set_selectable(True)
        body.set_justify(Gtk.Justification.CENTER)
        box.append(body)

    copy_button = None

    if code:
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_monospace(True)
        view.add_css_class("lab-code")
        view.get_buffer().set_text(code)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(view)
        scroller.set_min_content_height(min(60 + 20 * code.count("\n"), 320))
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(360)
        box.append(scroller)

        copy_button = Gtk.Button()
        copy_content = Gtk.Box(spacing=8)
        copy_content.append(Gtk.Image.new_from_icon_name("edit-copy-symbolic"))
        copy_label = Gtk.Label(label="Copy")
        copy_content.append(copy_label)
        copy_button.set_child(copy_content)
        copy_button.add_css_class("suggested-action")

        def copy(_button):
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set_content(Gdk.ContentProvider.new_for_value(code))
            copy_label.set_text("Copied!")
            GLib.timeout_add_seconds(2, lambda: copy_label.set_text("Copy") or False)

        copy_button.connect("clicked", copy)

    buttons = Gtk.Box(spacing=12)
    buttons.set_halign(Gtk.Align.CENTER)
    if copy_button:
        buttons.append(copy_button)
    close_button = Gtk.Button(label="Close")
    close_button.connect("clicked", lambda _button: window.close())
    buttons.append(close_button)
    box.append(buttons)

    window.set_child(box)
    window.present()

    timeout = os.environ.get("LAB_MESSAGE_TIMEOUT")
    if timeout:
        GLib.timeout_add_seconds(int(timeout), lambda: window.close() or False)

    if os.environ.get("LAB_MESSAGE_SELFTEST") and copy_button:
        def selftest():
            copy_button.emit("clicked")
            clipboard = Gdk.Display.get_default().get_clipboard()

            def done(source, result):
                print("CLIPBOARD:" + repr(source.read_text_finish(result)), flush=True)
                window.close()

            clipboard.read_text_async(None, done)
            return False

        GLib.timeout_add(800, selftest)


def main():
    title, text, code = load_message(sys.argv[1])
    app = Gtk.Application(
        application_id="com.school.LabLiveMessage",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.connect("activate", lambda application: activate(application, title, text, code))
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())
