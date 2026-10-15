#!/usr/bin/env python3
"""The "Check for Lab Updates" window: starts the updater and shows the result.

Runs as whoever is logged in. Starting lab-updater.service without a password
is allowed by /etc/polkit-1/rules.d/45-lab-updater.rules.
"""

import json
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib


STATUS_FILE = "/var/lib/lab-updater/status.json"
APPLIED_DIR = os.environ.get("LAB_UPDATER_APPLIED_DIR", "/var/lib/lab-updater/applied")
CONFIG_FILE = os.environ.get("LAB_UPDATER_CONFIG", "/etc/lab-updater/config")

MESSAGES = {
    "ok": "This laptop is up to date.",
    "offline": "Could not reach the update server.\nCheck the Wi-Fi connection and try again.",
    "failed": "An update could not be installed.\nPlease tell your teacher.",
    "rejected": "An update was blocked for security reasons.\nPlease tell your teacher.",
    "error": "Something went wrong while checking for updates.\nPlease tell your teacher.",
}


def read_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as status_file:
            return json.load(status_file)
    except (OSError, ValueError):
        return {}


def version_text():
    """e.g. "This laptop is on update 0011 (finish-test-accounts)"."""
    try:
        applied = sorted(name for name in os.listdir(APPLIED_DIR) if name[:4].isdigit())
    except OSError:
        applied = []

    if not applied:
        text = "No lab updates installed yet"
    else:
        number, _, name = applied[-1].partition("-")
        text = f"This laptop is on update {number}" + (f" ({name})" if name else "")

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
            for line in config_file:
                key, _, value = line.strip().partition("=")
                if key == "BRANCH" and value and value != "main":
                    text += f"\n{value} channel"
    except OSError:
        pass

    return text


class UpdateWindow(Gtk.ApplicationWindow):

    def __init__(self, app):
        super().__init__(
            application=app,
            title="Check for Lab Updates",
            default_width=460,
            default_height=260,
        )

        self.set_resizable(False)

        main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
        )
        main_box.set_margin_top(28)
        main_box.set_margin_bottom(28)
        main_box.set_margin_start(32)
        main_box.set_margin_end(32)

        title = Gtk.Label()
        title.set_markup("<span size='x-large' weight='bold'>Lab Updates</span>")
        main_box.append(title)

        self.spinner = Gtk.Spinner()
        main_box.append(self.spinner)

        self.status_label = Gtk.Label()
        self.status_label.set_wrap(True)
        self.status_label.set_justify(Gtk.Justification.CENTER)
        main_box.append(self.status_label)

        self.version_label = Gtk.Label(label=version_text())
        self.version_label.add_css_class("dim-label")
        self.version_label.set_justify(Gtk.Justification.CENTER)
        main_box.append(self.version_label)

        self.close_button = Gtk.Button(label="Close")
        self.close_button.set_halign(Gtk.Align.CENTER)
        self.close_button.connect("clicked", lambda button: self.close())
        main_box.append(self.close_button)

        self.set_child(main_box)

        self.start_check()

    def start_check(self):
        self.spinner.start()
        self.status_label.set_text(
            "Checking for updates...\n\n"
            "You can keep working. Installing updates may take a while."
        )

        threading.Thread(target=self.run_updater, daemon=True).start()

    def run_updater(self):
        # Blocks until the update run finishes (or joins one already running).
        result = subprocess.run(
            ["/usr/bin/systemctl", "start", "lab-updater.service"],
            capture_output=True,
            text=True,
            check=False,
        )

        GLib.idle_add(self.show_result, result.returncode, result.stderr.strip())

    def show_result(self, returncode, error_text):
        self.spinner.stop()

        status = read_status()
        result = status.get("result", "error")
        message = MESSAGES.get(result, MESSAGES["error"])
        installed = status.get("installed_this_run", [])

        if result == "ok" and installed:
            message = f"Installed {len(installed)} update(s):\n" + "\n".join(installed)

        if returncode != 0 and not status:
            message = MESSAGES["error"] + (f"\n\n{error_text}" if error_text else "")

        self.status_label.set_text(message)
        self.version_label.set_text(version_text())

        return GLib.SOURCE_REMOVE


class UpdateApplication(Gtk.Application):

    def __init__(self):
        super().__init__(
            application_id="com.school.CheckForLabUpdates"
        )

    def do_activate(self):
        window = UpdateWindow(self)
        window.present()


app = UpdateApplication()
sys.exit(app.run())
