#!/usr/bin/env python3
"""Tests for 0061-opencode-tutor: the tutor rules and `ics3u-agents tutor`.
Temp folders only; no root, no network.

    python3 -I update-repo/tests/test_0061_opencode_tutor.py
"""

import os
import stat
import subprocess
import tempfile
import unittest


def read(path):
    with open(path) as f:
        return f.read()


HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0061-opencode-tutor")
CMD = os.path.join(UPDATE, "files", "usr", "local", "bin", "ics3u-agents")
TUTOR = os.path.join(UPDATE, "files", "usr", "local", "share", "ics3u-cp", "AGENTS-tutor.md")
CP = os.path.join(HERE, "..", "updates", "0060-opencode", "files", "usr", "local", "share", "ics3u-cp", "AGENTS.md")
INSTALL = os.path.join(UPDATE, "install.sh")


class TutorRules(unittest.TestCase):
    def test_marker_and_section(self):
        text = read(TUTOR)
        self.assertTrue(text.startswith("<!-- ICS3U-TUTOR-v1"))
        self.assertIn("## My assignment (I fill this in once)", text)
        self.assertNotIn("draft", text.splitlines()[0].lower())

    def test_never_writes_code(self):
        text = read(TUTOR)
        self.assertIn("Never write, edit, create or delete files", text)
        self.assertIn("Never write code for my assignment", text)
        self.assertIn("Never run commands", text)


class AgentsCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        share = os.path.join(self.tmp.name, "share")
        os.mkdir(share)
        with open(os.path.join(share, "AGENTS.md"), "w") as f:
            f.write(read(CP))
        with open(os.path.join(share, "AGENTS-tutor.md"), "w") as f:
            f.write(read(TUTOR))
        text = read(CMD)
        self.assertIn("DIR=/usr/local/share/ics3u-cp\n", text)
        self.cmd = os.path.join(self.tmp.name, "ics3u-agents")
        with open(self.cmd, "w") as f:
            f.write(text.replace("DIR=/usr/local/share/ics3u-cp", "DIR='" + share + "'"))
        os.chmod(self.cmd, 0o755)
        self.project = os.path.join(self.tmp.name, "My Project")
        os.mkdir(self.project)
        self.target = os.path.join(self.project, "AGENTS.md")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, *args):
        return subprocess.run([self.cmd, *args], capture_output=True, text=True, cwd=self.project)

    def test_tutor_copies_once(self):
        r = self.run_cmd("tutor")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(),
                         'AGENTS.md copied: fill in the "My assignment" section and change nothing else.')
        self.assertEqual(read(self.target), read(TUTOR))
        with open(self.target, "a") as f:
            f.write("mine\n")
        self.assertEqual(self.run_cmd("tutor").returncode, 1)
        self.assertEqual(self.run_cmd().returncode, 1)
        self.assertTrue(read(self.target).endswith("mine\n"))

    def test_plain_still_culminating(self):
        r = self.run_cmd()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(),
                         'AGENTS.md copied: fill in the "My project" section and change nothing else.')
        self.assertEqual(read(self.target), read(CP))

    def test_unknown_word_shows_usage(self):
        r = self.run_cmd("tutr")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ics3u-agents tutor", r.stderr)
        self.assertFalse(os.path.lexists(self.target))

    def test_never_follows_a_symlink(self):
        other = os.path.join(self.tmp.name, "other.txt")
        with open(other, "w") as f:
            f.write("keep\n")
        os.symlink(other, self.target)
        self.assertEqual(self.run_cmd("tutor").returncode, 1)
        self.assertEqual(read(other), "keep\n")


class Install(unittest.TestCase):
    def test_scripts(self):
        for path in (INSTALL, CMD):
            subprocess.run(["bash", "-n", path], check=True)
            self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR, path)
        text = read(INSTALL)
        self.assertIn('source "$LAB_UPDATER_HELPERS"', text)
        self.assertIn("/usr/local/share/ics3u-cp/AGENTS-tutor.md 644", text)
        self.assertIn("/usr/local/bin/ics3u-agents 755", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
