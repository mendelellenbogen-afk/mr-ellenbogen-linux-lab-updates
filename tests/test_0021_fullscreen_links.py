#!/usr/bin/env python3
"""Tests for 0021-fullscreen-links: the 0008/0019/0020 rules on the new
listener, the full-screen/volume/close routing, and lab-present itself with a
fake Firefox and wpctl. No network, no root, no real browser.

    python3 -I update-repo/tests/test_0021_fullscreen_links.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "updates", "0021-fullscreen-links", "files", "usr", "local", "lib", "lab-messages")
LISTENER = os.path.join(FILES, "lab-messages-listener.py")
PRESENT = os.path.join(FILES, "lab-present")

sys.path.insert(0, HERE)
import test_0008_live_messages as t8   # noqa: E402
import test_0019_admin_only_messages as t19   # noqa: E402
import test_0020_open_links as t20   # noqa: E402

listener = t19.load("listener21", LISTENER)
for module in (t8, t19, t20):
    module.listener = listener


class Old0008Rules(t8.LiveMessages):
    pass


class Old0019Rules(t19.AdminOnly):
    pass


class Old0019Config(t19.Config):
    pass


class Old0020Rules(t20.OpenLinks):
    pass


class Routing(t20.OpenLinks):

    def send(self, **fields):
        message = {"id": "r" + str(len(self.commands)), "title": "T", "text": "", "code": ""}
        message.update(fields)
        listener.show(message, admins_only=fields.pop("admins_only", False))

    def by_program(self):
        return [(user, os.path.basename(program), last) for user, program, last in self.commands]

    def test_fullscreen_link_goes_to_lab_present_with_volume(self):
        self.send(open="https://www.youtube.com/embed/x?autoplay=1", fullscreen=True, volume=70)
        self.assertEqual(len(self.commands), 3)
        self.assertTrue(all(c[1] == listener.PRESENT and c[2] == "https://www.youtube.com/embed/x?autoplay=1"
                            for c in self.commands))
        self.assertEqual(self.windows, [])      # no pop-up

    def test_fullscreen_arguments(self):
        seen = []
        real_run_as = listener.run_as
        listener.run_as = lambda user, command: seen.append(command) or True
        try:
            self.send(open="https://a.com", fullscreen=True, volume=70)
        finally:
            listener.run_as = real_run_as
        self.assertEqual(seen[0], [listener.PRESENT, "--volume", "70", "https://a.com"])

    def test_close_and_volume_alone_run_lab_present_without_popup(self):
        self.send(close=True)
        self.send(volume=40)
        self.assertEqual({c[1] for c in self.commands}, {listener.PRESENT})
        self.assertEqual(len(self.commands), 6)
        self.assertEqual(self.windows, [])

    def test_volume_with_plain_link_uses_the_normal_browser(self):
        self.send(open="https://a.com", volume=50)
        self.assertEqual([c[1] for c in self.commands], [listener.PRESENT, "/usr/bin/xdg-open"] * 3)

    def test_bad_volume_values_ignored(self):
        for volume in (-1, 101, 50.5, "70", True, None, [70]):
            self.assertIsNone(listener.safe_volume(volume), volume)
        self.commands.clear()
        self.send(volume="70; rm -rf /")
        self.assertEqual(len(self.windows), 3)   # nothing to do, so the pop-up is shown

    def test_fullscreen_must_be_exactly_true(self):
        self.send(open="https://a.com", fullscreen="yes")
        self.assertEqual({c[1] for c in self.commands}, {"/usr/bin/xdg-open"})

    def test_unsafe_link_never_reaches_lab_present(self):
        self.send(open="file:///etc/shadow", fullscreen=True)
        self.assertNotIn(listener.PRESENT, [c[1] for c in self.commands])

    def test_close_admins_only(self):
        self.send(close=True, admins_only=True)
        self.assertEqual([c[0] for c in self.commands], ["administrator"])


FAKE_FIREFOX = """#!/bin/bash
echo "$*" >> "$LOG"
exec -a "firefox $*" "$REALBIN/firefox" -e "sleep 30"     # a copy of perl named firefox
"""
FAKE_WPCTL = """#!/bin/bash
echo "wpctl $*" >> "$LOG"
"""


class LabPresent(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.home = os.path.join(self.dir, "home")
        os.makedirs(os.path.join(self.dir, "bin"))
        os.makedirs(os.path.join(self.dir, "realbin"))
        shutil.copy("/usr/bin/perl", os.path.join(self.dir, "realbin", "firefox"))
        for name, text in (("firefox", FAKE_FIREFOX), ("wpctl", FAKE_WPCTL)):
            path = os.path.join(self.dir, "bin", name)
            with open(path, "w") as tool:
                tool.write(text)
            os.chmod(path, 0o755)
        self.log = os.path.join(self.dir, "log")
        self.env = dict(os.environ, HOME=self.home, LOG=self.log, REALBIN=os.path.join(self.dir, "realbin"),
                        PATH=os.path.join(self.dir, "bin") + ":" + os.environ["PATH"],
                        LAB_PRESENT_FIREFOX=os.path.join(self.dir, "bin", "firefox"))
        self.profile = os.path.join(self.home, "snap", "firefox", "common", "lab-fullscreen-profile")

    def tearDown(self):
        subprocess.run(["pkill", "-f", "--", f"--profile {self.profile}"])
        shutil.rmtree(self.dir)

    def present(self, *args):
        process = subprocess.Popen(["bash", PRESENT, *args], env=self.env)
        time.sleep(0.6)
        return process

    def log_lines(self):
        return open(self.log).read().splitlines() if os.path.exists(self.log) else []

    def running(self):
        return subprocess.run(["pgrep", "-f", "--", f"--profile {self.profile}"],
                              capture_output=True).returncode == 0

    def test_opens_kiosk_with_own_profile_and_autoplay(self):
        self.present("--volume", "70", "https://a.com/v")
        self.assertEqual(self.log_lines(), [
            "wpctl set-mute @DEFAULT_AUDIO_SINK@ 0", "wpctl set-volume @DEFAULT_AUDIO_SINK@ 70%",
            f"--kiosk --no-remote --profile {self.profile} https://a.com/v"])
        with open(os.path.join(self.profile, "user.js")) as prefs:
            self.assertIn('user_pref("media.autoplay.default", 0);', prefs.read())
        self.assertTrue(self.running_firefox())

    def test_new_link_replaces_the_previous_window_and_close_closes_it(self):
        first = self.present("https://a.com/1")
        self.present("https://a.com/2")
        self.assertIsNotNone(first.poll())               # the first Firefox is gone
        self.assertTrue(self.running_firefox())
        subprocess.run(["bash", PRESENT, "--close"], env=self.env, check=True)
        self.assertFalse(self.running_firefox())

    def test_youtube_style_rule_written(self):
        self.present("https://www.youtube.com/watch?v=x")
        with open(os.path.join(self.profile, "chrome", "userContent.css")) as style:
            self.assertIn('@-moz-document domain("youtube.com")', style.read())
        with open(os.path.join(self.profile, "user.js")) as prefs:
            self.assertIn("toolkit.legacyUserProfileCustomizations.stylesheets", prefs.read())

    def test_close_leaves_other_programs_alone(self):
        # A non-Firefox process whose command line mentions the profile.
        other = subprocess.Popen(["bash", "-c", f"sleep 30 # --profile {self.profile} x"])
        self.present("https://a.com/1")
        subprocess.run(["bash", PRESENT, "--close"], env=self.env, check=True)
        self.assertFalse(self.running_firefox())
        self.assertIsNone(other.poll())
        other.kill()

    def running_firefox(self):
        return subprocess.run(["pgrep", "-x", "firefox"], capture_output=True).returncode == 0 and any(
            f"--profile {self.profile}" in open(f"/proc/{pid}/cmdline").read().replace("\0", " ")
            for pid in subprocess.run(["pgrep", "-x", "firefox"], capture_output=True, text=True).stdout.split())

    def test_bad_volume_and_bad_link_do_nothing(self):
        result = subprocess.run(["bash", PRESENT, "--volume", "70%;x", "file:///etc/passwd"],
                                env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.log_lines(), [])

    def test_close_when_nothing_is_open(self):
        self.assertEqual(subprocess.run(["bash", PRESENT, "--close"], env=self.env).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
