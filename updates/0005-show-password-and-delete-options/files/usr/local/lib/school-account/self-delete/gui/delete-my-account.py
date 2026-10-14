#!/usr/bin/env python3

import datetime
import subprocess
import sys

import dbus
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib


BUS_NAME = "com.school.StudentSelfDelete"
OBJECT_PATH = "/com/school/StudentSelfDelete"
INTERFACE = "com.school.StudentSelfDelete"


def friendly_date(text):
    date = datetime.date.fromisoformat(text)
    return f"{date:%A, %B} {date.day}, {date:%Y}"


def service():
    bus = dbus.SystemBus()
    return dbus.Interface(bus.get_object(BUS_NAME, OBJECT_PATH), INTERFACE)


class DeleteAccountWindow(Gtk.ApplicationWindow):

    def __init__(self, app):
        super().__init__(
            application=app,
            title="Delete My Account",
            default_width=520,
            default_height=480,
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
        title.set_markup("<span size='x-large' weight='bold'>Delete My Account</span>")
        title.set_halign(Gtk.Align.CENTER)

        main_box.append(title)

        warning = Gtk.Label(
            label=(
                "This will permanently delete your account "
                "and the files stored in your home folder.\n\n"
                "This action cannot be undone."
            )
        )
        warning.set_wrap(True)
        warning.set_justify(Gtk.Justification.CENTER)
        main_box.append(warning)

        self.scheduled_label = Gtk.Label()
        self.scheduled_label.set_wrap(True)
        self.scheduled_label.set_justify(Gtk.Justification.CENTER)
        main_box.append(self.scheduled_label)

        when_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        when_box.set_halign(Gtk.Align.CENTER)

        when_label = Gtk.Label(label="When should your account be deleted?")
        when_box.append(when_label)

        # Radio buttons; neither is pre-selected, so the choice is deliberate.
        self.later_option = Gtk.CheckButton(
            label="Delete in 7 days (keep using it until then)"
        )
        self.now_option = Gtk.CheckButton(
            label="Delete now (you will be logged out)"
        )
        self.now_option.set_group(self.later_option)
        when_box.append(self.later_option)
        when_box.append(self.now_option)
        main_box.append(when_box)

        instruction = Gtk.Label(
            label="To confirm, type DELETE below:"
        )
        instruction.set_halign(Gtk.Align.CENTER)
        main_box.append(instruction)

        self.confirm_entry = Gtk.Entry()
        self.confirm_entry.set_placeholder_text("Type DELETE")
        self.confirm_entry.set_max_length(6)
        self.confirm_entry.set_halign(Gtk.Align.CENTER)
        main_box.append(self.confirm_entry)

        self.status_label = Gtk.Label()
        self.status_label.set_wrap(True)
        self.status_label.set_justify(Gtk.Justification.CENTER)
        main_box.append(self.status_label)

        button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        button_box.set_halign(Gtk.Align.CENTER)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", self.on_cancel)

        self.delete_button = Gtk.Button(label="Delete My Account")
        self.delete_button.connect("clicked", self.on_delete)

        button_box.append(cancel_button)
        button_box.append(self.delete_button)

        main_box.append(button_box)

        self.set_child(main_box)

        self.show_existing_schedule()

    def show_existing_schedule(self):
        try:
            when = str(service().get_scheduled_deletion())
        except Exception:
            when = ""

        if when:
            self.scheduled_label.set_markup(
                f"<b>Your account is already scheduled to be deleted on "
                f"{GLib.markup_escape_text(friendly_date(when))}.</b>\n"
                f"You can still choose to delete it now."
            )
            self.later_option.set_sensitive(False)

    def on_cancel(self, button):
        self.close()

    def on_delete(self, button):
        if not (self.later_option.get_active() or self.now_option.get_active()):
            self.status_label.set_text(
                "Choose when your account should be deleted."
            )
            return

        confirmation = self.confirm_entry.get_text()

        if confirmation != "DELETE":
            self.status_label.set_text(
                "Confirmation failed. Type DELETE exactly."
            )
            return

        self.status_label.set_text(
            "Submitting account deletion request..."
        )

        later = self.later_option.get_active()

        try:
            if later:
                result = str(service().request_self_delete_later())
            else:
                result = str(service().request_self_delete())

        except Exception as error:
            self.status_label.set_text(
                f"Unable to submit deletion request:\n{error}"
            )
            return

        if later and result.startswith("Deletion scheduled"):
            when = result.rstrip(".").rsplit(" on ", 1)[-1]
            self.status_label.set_text(
                f"Your account will be deleted on {friendly_date(when)}.\n\n"
                f"Save any work you want to keep somewhere else "
                f"(a USB drive or Google Drive) before then."
            )
            self.delete_button.set_sensitive(False)

        elif result.startswith("Deletion scheduled"):
            self.status_label.set_text(
                "Your account has been scheduled for deletion.\n\n"
                "You will now be logged out."
            )

            GLib.timeout_add_seconds(
                3,
                self.logout_user,
            )

        else:
            self.status_label.set_text(result)

    def logout_user(self):
        subprocess.Popen(
            [
                "/usr/bin/gnome-session-quit",
                "--logout",
                "--no-prompt",
            ]
        )

        return GLib.SOURCE_REMOVE


class DeleteAccountApplication(Gtk.Application):

    def __init__(self):
        super().__init__(
            application_id="com.school.DeleteMyAccount"
        )

    def do_activate(self):
        window = DeleteAccountWindow(self)
        window.present()


app = DeleteAccountApplication()
sys.exit(app.run())
