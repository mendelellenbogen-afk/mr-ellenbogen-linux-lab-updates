#!/usr/bin/env python3
# D-Bus service (root) behind the login screen's "Admin: clear student
# accounts" button (lab update 0050). Only the GDM login screen may call it
# (polkit rule 31-school-clear-accounts.rules), and only with the
# administrator password.
#
# check_admin(password) -> (ok, message, token, count, logged_in)
#   checks the administrator password and says how many accounts would be
#   deleted. A wrong password waits 2 s; 5 wrong in a row lock it for 5 min.
# clear_accounts(token) -> message
#   deletes them (clear_accounts.py). The token is single-use, belongs to the
#   caller that got it, and expires after 2 minutes.

import secrets
import sys
import threading
import time

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

sys.path.insert(0, "/usr/local/lib/school-account")
import clear_accounts  # noqa: E402


BUS_NAME = "com.school.ClearAccounts"
OBJECT_PATH = "/com/school/ClearAccounts"
INTERFACE = "com.school.ClearAccounts"
POLKIT_ACTION = "com.school.clear-accounts"

TOKEN_LIFETIME = 120
WRONG_PASSWORD_DELAY = 2
MAX_WRONG = 5
LOCK_SECONDS = 300


def log(message):
    print(message, flush=True)


class ClearAccountsService(dbus.service.Object):

    def __init__(self, bus):
        super().__init__(bus, OBJECT_PATH)
        self.busy = threading.Lock()
        self.tokens = {}          # token -> (sender, expires)
        self.wrong = 0
        self.locked_until = 0.0

    def authorized(self, sender):
        authority = dbus.Interface(
            dbus.SystemBus().get_object("org.freedesktop.PolicyKit1",
                                        "/org/freedesktop/PolicyKit1/Authority"),
            "org.freedesktop.PolicyKit1.Authority")
        result, _challenge, _details = authority.CheckAuthorization(
            ("system-bus-name", {"name": sender}), POLKIT_ACTION, {}, 0, "")
        return bool(result)

    def run_in_thread(self, work, reply, answer_for):
        # One check or clear at a time; the slow part runs off the D-Bus loop.
        if not self.busy.acquire(blocking=False):
            reply(*answer_for("Busy. Please wait and try again."))
            return

        def thread():
            try:
                answer = work()
            except Exception as failure:
                log(f"ERROR: {failure}")
                answer = answer_for(f"ERROR: {failure}")
            finally:
                self.busy.release()
            GLib.idle_add(lambda: reply(*answer) and False)

        threading.Thread(target=thread, daemon=True).start()

    def check(self, password, sender):
        now = time.monotonic()
        if now < self.locked_until:
            minutes = int((self.locked_until - now) // 60) + 1
            return (False, f"Too many wrong passwords. Try again in {minutes} min.", "", 0, 0)

        if not clear_accounts.check_admin_password(password):
            time.sleep(WRONG_PASSWORD_DELAY)
            self.wrong += 1
            log(f"Wrong administrator password ({self.wrong} in a row).")
            if self.wrong >= MAX_WRONG:
                self.wrong = 0
                self.locked_until = time.monotonic() + LOCK_SECONDS
                return (False, "Too many wrong passwords. Try again in 5 min.", "", 0, 0)
            return (False, "That is not the administrator password.", "", 0, 0)

        self.wrong = 0
        to_delete, _skipped = clear_accounts.accounts_to_clear()
        logged_in = sum(1 for account in to_delete if clear_accounts.has_processes(account.pw_uid))
        if not to_delete:
            return (True, "There are no student accounts to delete.", "", 0, 0)

        token = secrets.token_hex(16)
        self.tokens = {t: v for t, v in self.tokens.items() if v[1] > now}
        self.tokens[token] = (sender, now + TOKEN_LIFETIME)
        return (True, "OK", token, len(to_delete), logged_in)

    def clear(self, token, sender):
        owner, expires = self.tokens.pop(token, (None, 0))
        if owner != sender or time.monotonic() > expires:
            return ("That took too long. Enter the administrator password again.",)

        log("Clearing student accounts (administrator password given on the login screen).")
        message = clear_accounts.clear_all(log)
        log(message)
        return (message,)

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="bssuu",
                         sender_keyword="sender", async_callbacks=("reply", "error"))
    def check_admin(self, password, sender=None, reply=None, error=None):
        if not self.authorized(sender):
            reply(False, "ERROR: Not authorized.", "", 0, 0)
            return
        self.run_in_thread(lambda: self.check(str(password), sender), reply,
                           lambda message: (False, message, "", 0, 0))

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender", async_callbacks=("reply", "error"))
    def clear_accounts(self, token, sender=None, reply=None, error=None):
        if not self.authorized(sender):
            reply("ERROR: Not authorized.")
            return
        self.run_in_thread(lambda: self.clear(str(token), sender), reply,
                           lambda message: (message,))


if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    dbus.mainloop.glib.threads_init()

    bus = dbus.SystemBus()
    name = dbus.service.BusName(BUS_NAME, bus)

    ClearAccountsService(bus)

    GLib.MainLoop().run()
