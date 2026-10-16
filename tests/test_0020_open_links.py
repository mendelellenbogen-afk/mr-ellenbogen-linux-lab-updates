#!/usr/bin/env python3
"""Tests for 0020-open-links: every 0008 and 0019 rule still holds on the new
listener, and "open" opens only plain http(s) links. No network, no root.

    python3 -I update-repo/tests/test_0020_open_links.py
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LISTENER = os.path.join(HERE, "..", "updates", "0020-open-links", "files",
                        "usr", "local", "lib", "lab-messages", "lab-messages-listener.py")

sys.path.insert(0, HERE)
import test_0008_live_messages as t8   # noqa: E402
import test_0019_admin_only_messages as t19   # noqa: E402

listener = t19.load("listener20", LISTENER)
t8.listener = listener
t19.listener = listener


class Old0008Rules(t8.LiveMessages):
    pass


class Old0019Rules(t19.AdminOnly):
    pass


class Old0019Config(t19.Config):
    pass


class OpenLinks(t19.AdminOnly):

    def setUp(self):
        super().setUp()
        self.commands = []
        test = self
        fail_for = self.fail_open_for = set()

        class FakeSubprocess:
            @staticmethod
            def run(args, **kwargs):
                if args[0] == "/usr/bin/systemd-run":
                    user = next(a for a in args if a.startswith("--machine=")).split("=")[1].rstrip("@")
                    command = args[args.index("--user") + 1:]
                    test.commands.append((user, command[0], command[-1]))
                    if command[0] == "/usr/bin/python3":
                        test.windows.append(user)
                    ok = not (command[0] == "/usr/bin/xdg-open" and user in fail_for)
                    return subprocess.CompletedProcess(args, 0 if ok else 1, "", "")
                return subprocess.run(args, **kwargs)

        listener.subprocess = FakeSubprocess

    def message(self, message_id, link, text=""):
        return {"id": message_id, "title": "T", "text": text, "code": link or "", "open": link}

    def test_link_opens_for_everyone_without_a_popup(self):
        listener.show(self.message("a1", "https://youtu.be/BBGEG21CGo0?si=x"))
        self.assertEqual(self.commands, [(u, "/usr/bin/xdg-open", "https://youtu.be/BBGEG21CGo0?si=x")
                                         for u in ("administrator", "studenttest1", "tdsb-123456789")])

    def test_link_with_text_also_shows_the_popup(self):
        listener.show(self.message("a2", "https://example.com", text="Watch this"))
        self.assertEqual([c[1] for c in self.commands], ["/usr/bin/xdg-open", "/usr/bin/python3"] * 3)

    def test_link_admins_only(self):
        listener.show(self.message("a3", "https://example.com"), admins_only=True)
        self.assertEqual([c[0] for c in self.commands], ["administrator"])

    def test_browser_failure_falls_back_to_popup_for_that_user_only(self):
        self.fail_open_for.add("studenttest1")
        listener.show(self.message("a4", "https://example.com"))
        popups = [c[0] for c in self.commands if c[1] == "/usr/bin/python3"]
        self.assertEqual(popups, ["studenttest1"])

    def test_unsafe_links_are_never_opened(self):
        for i, link in enumerate(["file:///etc/passwd", "javascript:alert(1)", "ftp://x.org/a",
                                  "https://", "http://exa mple.com", "https://a.com/\n--x",
                                  "-https://a.com", "smb://server/share", "https://a.com/" + "a" * 2001,
                                  "apt://firefox", ["https://a.com"], 7]):
            self.commands.clear()
            listener.show(self.message(f"b{i}", link))
            self.assertNotIn("/usr/bin/xdg-open", [c[1] for c in self.commands], link)
            self.assertEqual(len(self.commands), 3, link)   # the pop-up is shown instead

    def test_safe_link_accepts_normal_addresses(self):
        for link in ("https://youtu.be/BBGEG21CGo0?si=mwmXDW0zaQ3xAp9y", "HTTP://Example.com/a?b=c#d",
                     "https://docs.oracle.com/en/java/"):
            self.assertEqual(listener.safe_link(link), link)

    def test_signed_message_with_link_through_the_listener(self):
        self.deliver((t19.CLASS_TOPIC, self.body("c1")))
        self.assertTrue(all(c[1] == "/usr/bin/python3" for c in self.commands))


if __name__ == "__main__":
    unittest.main(verbosity=2)
