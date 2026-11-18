#!/usr/bin/env python3
"""Tests for 0060-opencode: the lab settings, the wrapper and ics3u-agents.
Temp folders only; no root, no network. The real OpenCode is replaced by a fake.

    python3 -I update-repo/tests/test_0060_opencode.py
"""

import json
import os
import re
import stat
import subprocess
import tempfile
import unittest


def read(path):
    with open(path) as f:
        return f.read()

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0060-opencode")
FILES = os.path.join(UPDATE, "files")
CONFIG = os.path.join(FILES, "etc", "opencode", "opencode.json")
WRAPPER = os.path.join(FILES, "usr", "local", "bin", "opencode")
AGENTS_CMD = os.path.join(FILES, "usr", "local", "bin", "ics3u-agents")
TEMPLATE = os.path.join(FILES, "usr", "local", "share", "ics3u-cp", "AGENTS.md")
INSTALL = os.path.join(UPDATE, "install.sh")

ALLOWED = {"hy4-flash-free", "deepseek-v4.1-flash-free", "beam-free", "longcat-2.5-free"}
TRAINING = {"big-pickle", "iceman-free", "inkling-2-small-free", "flint-40b-free",
            "mimo-v2.6-flash-free", "nemotron-3.5-lightning-free", "nemotron-3.5-super-vl-free"}


class Config(unittest.TestCase):
    def setUp(self):
        with open(CONFIG) as f:
            self.c = json.load(f)

    def test_default_model_and_switches(self):
        self.assertEqual(self.c["model"], "opencode/hy4-flash-free")
        self.assertEqual(self.c["share"], "disabled")
        self.assertEqual(self.c["update"], "disable")

    def test_only_opencode_provider_and_no_logins(self):
        p = [(s["action"], s["resource"], s["effect"]) for s in self.c["policies"]]
        # last match wins: deny everything first, then allow only the free tier
        self.assertLess(p.index(("provider.use", "*", "deny")), p.index(("provider.use", "opencode", "allow")))
        self.assertLess(p.index(("integration.use", "*", "deny")), p.index(("integration.use", "opencode", "allow")))
        self.assertIn(("integration.connect", "*", "deny"), p)
        self.assertNotIn(("integration.connect", "opencode", "allow"), p)
        self.assertEqual([x for x in p if x[2] == "allow"],
                         [("integration.use", "opencode", "allow"), ("provider.use", "opencode", "allow")])
        self.assertIn(("tool.use", "external_directory:*", "deny"), p)

    def test_training_models_hidden_allowed_ones_not(self):
        models = self.c["providers"]["opencode"]["models"]
        hidden = {m for m, v in models.items() if v.get("disabled")}
        self.assertTrue(TRAINING <= hidden)
        self.assertFalse(ALLOWED & hidden)

    def test_approvals_ask(self):
        rules = {(r["action"], r["resource"]): r["effect"] for r in self.c["permissions"]}
        for action in ("edit", "shell", "webfetch", "websearch", "external_directory"):
            self.assertEqual(rules[(action, "*")], "ask", action)
        self.assertNotIn("allow", rules.values())

    def test_no_secrets(self):
        text = read(CONFIG) + read(INSTALL) + read(WRAPPER)
        self.assertNotRegex(text, r"(?i)api[_-]?key|sk-[a-z0-9]|password|token")


class Wrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.real = os.path.join(self.tmp.name, "real-opencode")
        with open(self.real, "w") as f:
            f.write('#!/bin/bash\necho "CLAUDE=$OPENCODE_DISABLE_CLAUDE_CODE AUTO=$OPENCODE_DISABLE_AUTOUPDATE ARGS=$*"\n')
        os.chmod(self.real, 0o755)
        text = read(WRAPPER)
        self.assertIn("REAL=/usr/local/lib/opencode/2.3.2/opencode\n", text)
        self.wrapper = os.path.join(self.tmp.name, "opencode")
        with open(self.wrapper, "w") as f:
            f.write(text.replace("REAL=/usr/local/lib/opencode/2.3.2/opencode", "REAL='" + self.real + "'"))
        os.chmod(self.wrapper, 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_wrapper(self, *args):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.tmp.name}
        return subprocess.run([self.wrapper, *args], capture_output=True, text=True, env=env)

    def test_plain_start_is_standalone_with_env(self):
        r = self.run_wrapper()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "CLAUDE=1 AUTO=1 ARGS=--standalone")

    def test_args_passed_through(self):
        r = self.run_wrapper("run", "add a button", "-m", "opencode/beam-free")
        self.assertEqual(r.stdout.strip(), "CLAUDE=1 AUTO=1 ARGS=--standalone run add a button -m opencode/beam-free")

    def test_server_choice_kept(self):
        self.assertEqual(self.run_wrapper("--server", "http://127.0.0.1:4096").stdout.strip(),
                         "CLAUDE=1 AUTO=1 ARGS=--server http://127.0.0.1:4096")
        self.assertEqual(self.run_wrapper("--standalone").stdout.strip(), "CLAUDE=1 AUTO=1 ARGS=--standalone")

    def test_refuses_auto_and_updates(self):
        for args in (["--auto"], ["run", "--auto", "x"], ["upgrade"], ["update"], ["uninstall"]):
            r = self.run_wrapper(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(r.stdout, "", args)


class AgentsCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        text = read(AGENTS_CMD)
        self.assertIn("TEMPLATE=/usr/local/share/ics3u-cp/AGENTS.md\n", text)
        self.cmd = os.path.join(self.tmp.name, "ics3u-agents")
        with open(self.cmd, "w") as f:
            f.write(text.replace("TEMPLATE=/usr/local/share/ics3u-cp/AGENTS.md", "TEMPLATE='" + TEMPLATE + "'"))
        os.chmod(self.cmd, 0o755)
        self.project = os.path.join(self.tmp.name, "MyApp")
        os.mkdir(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self):
        return subprocess.run([self.cmd], capture_output=True, text=True, cwd=self.project)

    def test_copies_once_then_refuses(self):
        r = self.run_cmd()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertIn("My project", r.stdout)
        target = os.path.join(self.project, "AGENTS.md")
        self.assertEqual(read(target), read(TEMPLATE))
        with open(target, "a") as f:
            f.write("student edits\n")
        r = self.run_cmd()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(read(target).endswith("student edits\n"))

    def test_never_follows_a_symlink(self):
        other = os.path.join(self.tmp.name, "other.txt")
        with open(other, "w") as f:
            f.write("keep\n")
        os.symlink(other, os.path.join(self.project, "AGENTS.md"))
        self.assertEqual(self.run_cmd().returncode, 1)
        self.assertEqual(read(other), "keep\n")


class Install(unittest.TestCase):
    def test_template_is_the_teachers_rules(self):
        text = read(TEMPLATE)
        self.assertTrue(text.startswith("<!-- ICS3U-CP-AGENT-v1"))
        self.assertIn("## My project (I fill this in once)", text)

    def test_pinned_download_is_checked(self):
        text = read(INSTALL)
        self.assertIn("VERSION=2.3.2\n", text)
        self.assertRegex(text, r"\nSHA256=[0-9a-f]{64}\n")
        self.assertIn('sha256sum -c --quiet -', text)
        self.assertIn("releases/download/v$VERSION/opencode-linux-x64.tar.gz", text)
        # the downloaded file is checked before it is unpacked
        self.assertLess(text.index("sha256sum -c"), text.index("tar -xzf"))

    def test_scripts_are_executable_bash(self):
        for path in (INSTALL, WRAPPER, AGENTS_CMD):
            subprocess.run(["bash", "-n", path], check=True)
        for path in (WRAPPER, AGENTS_CMD):
            self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR, path)


if __name__ == "__main__":
    unittest.main(verbosity=1)
