#!/usr/bin/env python3
# D-Bus service (root) behind the login screen's "Login to TDSB to create your
# account" panel. Only the GDM login screen may call it (polkit rule
# 30-school-account-gdm.rules).
#
# create_tdsb_account(student_id, password_fd):
#   1. checks the ID is 9 digits and has no account yet,
#   2. tries to join TDSB-WIFI with the ID and password (the check),
#   3. if TDSB-WIFI accepts them, creates account "s"+ID via create-student.

import os
import subprocess
import sys
import threading

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

sys.path.insert(0, "/usr/local/lib/school-account")
import tdsb_wifi  # noqa: E402


BUS_NAME = "com.school.StudentAccount"
OBJECT_PATH = "/com/school/StudentAccount"
INTERFACE = "com.school.StudentAccount"
POLKIT_ACTION = "com.school.student-account.create"
CREATE_HELPER = "/usr/local/lib/school-account/create-student"


class StudentAccountService(dbus.service.Object):

    def __init__(self, bus):
        super().__init__(bus, OBJECT_PATH)
        self.busy = threading.Lock()

    def check_authorization(self, sender):
        bus = dbus.SystemBus()

        authority = dbus.Interface(
            bus.get_object(
                "org.freedesktop.PolicyKit1",
                "/org/freedesktop/PolicyKit1/Authority"
            ),
            "org.freedesktop.PolicyKit1.Authority"
        )

        subject = ("system-bus-name", {"name": sender})

        authorized, challenge, details = authority.CheckAuthorization(
            subject,
            POLKIT_ACTION,
            {},
            0,
            ""
        )

        return bool(authorized)

    def read_password(self, password_fd):
        fd = password_fd.take()

        try:
            data = b""

            while True:
                chunk = os.read(fd, 4096)

                if not chunk:
                    break

                data += chunk

            return data.decode("utf-8").rstrip("\n")

        finally:
            os.close(fd)

    def create(self, student_id, password):
        if not tdsb_wifi.is_student_id(student_id):
            return "A student ID is 9 digits."

        username = tdsb_wifi.username_for(student_id)

        if subprocess.run(
            ["/usr/bin/id", "-u", username],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0:
            return "This student ID already has an account. Click it in the list below."

        try:
            accepted = tdsb_wifi.check_credentials(student_id, password)
        except tdsb_wifi.WifiError as error:
            return str(error)
        except Exception as error:
            print(f"Wi-Fi check failed: {error}", flush=True)
            return "Could not check with TDSB-WIFI. Please try again."

        if not accepted:
            return "TDSB-WIFI did not accept that student ID and password."

        result = subprocess.run(
            [CREATE_HELPER, student_id],
            input=password + "\n",
            text=True,
            capture_output=True,
        )

        if result.returncode != 0:
            return result.stderr.strip() or "ERROR: Account creation failed."

        return (
            f"Account created for {student_id}. "
            f"Click your student ID in the list to log in."
        )

    @dbus.service.method(
        INTERFACE,
        in_signature="sh",
        out_signature="s",
        sender_keyword="sender",
        async_callbacks=("reply", "error"),
    )
    def create_tdsb_account(self, student_id, password_fd, sender=None, reply=None, error=None):
        if not self.check_authorization(sender):
            os.close(password_fd.take())
            reply("ERROR: Not authorized.")
            return

        password = self.read_password(password_fd)

        if not self.busy.acquire(blocking=False):
            reply("Another account is being created. Please wait and try again.")
            return

        # The Wi-Fi check takes several seconds; don't block the D-Bus loop.
        def work():
            try:
                message = self.create(str(student_id), password)
            except Exception as failure:
                message = f"ERROR: {failure}"
            finally:
                self.busy.release()

            GLib.idle_add(lambda: reply(message) and False)

        threading.Thread(target=work, daemon=True).start()


dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
dbus.mainloop.glib.threads_init()

bus = dbus.SystemBus()
name = dbus.service.BusName(BUS_NAME, bus)

StudentAccountService(bus)

GLib.MainLoop().run()
