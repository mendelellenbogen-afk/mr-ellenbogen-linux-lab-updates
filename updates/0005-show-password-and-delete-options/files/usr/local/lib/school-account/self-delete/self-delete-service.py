#!/usr/bin/env python3

import datetime
import os
import pwd
import subprocess

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

BUS_NAME = "com.school.StudentSelfDelete"
OBJECT_PATH = "/com/school/StudentSelfDelete"
INTERFACE = "com.school.StudentSelfDelete"

PENDING_DIR = "/run/school-account-self-delete"

# "Delete in 7 days" requests must survive reboots, so they live in /var/lib.
SCHEDULED_DIR = "/var/lib/school-account/self-delete-scheduled"
DELAY_DAYS = 7

PROTECTED_USERS = {
    "root",
    "administrator",
    "teststudent",
}


class StudentSelfDeleteService(dbus.service.Object):

    def __init__(self, bus):
        super().__init__(bus, OBJECT_PATH)

    def get_caller_info(self, sender):
        bus = dbus.SystemBus()

        dbus_obj = bus.get_object(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus"
        )

        dbus_iface = dbus.Interface(
            dbus_obj,
            "org.freedesktop.DBus"
        )

        uid = int(
            dbus_iface.GetConnectionUnixUser(sender)
        )

        try:
            account = pwd.getpwuid(uid)
        except KeyError:
            return None, None

        return account.pw_name, uid


    def validate_student(self, username, uid):
        if not username:
            return False, "ERROR: Unable to identify caller."

        if username in PROTECTED_USERS:
            return False, "ERROR: Protected account."

        try:
            account = pwd.getpwnam(username)
        except KeyError:
            return False, "ERROR: Account does not exist."

        if account.pw_uid != uid:
            return False, "ERROR: Caller identity mismatch."

        if account.pw_uid < 1000:
            return False, "ERROR: System account."

        if account.pw_dir != f"/home/{username}":
            return False, "ERROR: Invalid home directory."

        if account.pw_shell != "/bin/bash":
            return False, "ERROR: Account is not a standard student account."

        groups = subprocess.run(
            ["/usr/bin/id", "-Gn", username],
            capture_output=True,
            text=True,
            check=False,
        )

        if groups.returncode != 0:
            return False, "ERROR: Could not determine account groups."

        group_names = groups.stdout.split()

        if "users" not in group_names:
            return False, "ERROR: Account is not in the student group."

        return True, "OK"

    def create_pending_marker(self, username, uid):
        os.makedirs(
            PENDING_DIR,
            mode=0o700,
            exist_ok=True
        )

        final_path = os.path.join(
            PENDING_DIR,
            username
        )

        marker_contents = (
            f"UID={uid}\n"
            f"USERNAME={username}\n"
        )

        try:
            fd = os.open(
                final_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            return False, "ERROR: Account deletion is already pending."

        temp_path = None

        try:
            os.fchmod(fd, 0o600)

            with os.fdopen(fd, "w") as marker:
                marker.write(marker_contents)
                marker.flush()
                os.fsync(marker.fileno())

            os.chown(final_path, 0, 0)
            os.chmod(final_path, 0o600)

            return True, "OK"

        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass

            try:
                os.unlink(final_path)
            except FileNotFoundError:
                pass

            return False, "ERROR: Could not create deletion request."

    def scheduled_path(self, username):
        return os.path.join(SCHEDULED_DIR, username)

    def read_scheduled_date(self, username):
        try:
            with open(self.scheduled_path(username), "r", encoding="utf-8") as marker:
                for line in marker:
                    if line.startswith("DELETE_AFTER="):
                        return datetime.date.fromisoformat(line.split("=", 1)[1].strip())
        except (OSError, ValueError):
            pass
        return None

    def create_scheduled_marker(self, username, uid):
        os.makedirs(SCHEDULED_DIR, mode=0o700, exist_ok=True)
        os.chmod(SCHEDULED_DIR, 0o700)

        delete_after = datetime.date.today() + datetime.timedelta(days=DELAY_DAYS)
        path = self.scheduled_path(username)

        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return None, "ERROR: Account deletion is already scheduled."

        try:
            with os.fdopen(fd, "w") as marker:
                marker.write(
                    f"UID={uid}\n"
                    f"USERNAME={username}\n"
                    f"DELETE_AFTER={delete_after.isoformat()}\n"
                )
                marker.flush()
                os.fsync(marker.fileno())

            os.chown(path, 0, 0)
            os.chmod(path, 0o600)
            return delete_after, "OK"

        except Exception:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            return None, "ERROR: Could not create deletion request."

    @dbus.service.method(
        INTERFACE,
        in_signature="",
        out_signature="s",
        sender_keyword="sender_keyword"
    )
    def request_self_delete_later(self, sender_keyword=None):
        username, uid = self.get_caller_info(sender_keyword)

        valid, message = self.validate_student(username, uid)

        if not valid:
            return message

        delete_after, message = self.create_scheduled_marker(username, uid)

        if delete_after is None:
            return message

        return f"Deletion scheduled for '{username}' on {delete_after.isoformat()}."

    @dbus.service.method(
        INTERFACE,
        in_signature="",
        out_signature="s",
        sender_keyword="sender_keyword"
    )
    def get_scheduled_deletion(self, sender_keyword=None):
        """The caller's own scheduled deletion date (YYYY-MM-DD), or "" if none."""
        username, uid = self.get_caller_info(sender_keyword)

        if username is None:
            return ""

        when = self.read_scheduled_date(username)
        return when.isoformat() if when else ""

    @dbus.service.method(
        INTERFACE,
        in_signature="",
        out_signature="s",
        sender_keyword="sender_keyword"
    )
    def identify_caller(self, sender_keyword=None):
        username, uid = self.get_caller_info(sender_keyword)

        if username is None:
            return "UNKNOWN"

        return f"{username} (UID {uid})"

    @dbus.service.method(
        INTERFACE,
        in_signature="",
        out_signature="s",
        sender_keyword="sender_keyword"
    )
    def request_self_delete(self, sender_keyword=None):
        username, uid = self.get_caller_info(sender_keyword)

        valid, message = self.validate_student(
            username,
            uid
        )

        if not valid:
            return message

        success, message = self.create_pending_marker(
            username,
            uid
        )

        if not success:
            return message

        return (
            f"Deletion scheduled for '{username}'. "
            f"The account will be removed after logout."
        )


dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

bus = dbus.SystemBus()

name = dbus.service.BusName(
    BUS_NAME,
    bus
)

StudentSelfDeleteService(bus)

loop = GLib.MainLoop()
loop.run()
