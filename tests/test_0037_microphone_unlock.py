#!/usr/bin/env python3
"""Tests for 0037-microphone-unlock: the udev rules keep 0032's camera lock
line for line and drop the microphone lock; lab-capture-policy still controls
the camera and only explains the microphone; install.sh syntax and what it
restarts. No host devices touched.

    python3 -I update-repo/tests/test_0037_microphone_unlock.py
"""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

UPDATES = Path(__file__).resolve().parents[1] / 'updates'
BASE = UPDATES / '0037-microphone-unlock'
OLD = UPDATES / '0032-capture-lock'
RULES = BASE / 'files/etc/udev/rules.d/72-lab-capture.rules'
OLD_RULES = OLD / 'files/etc/udev/rules.d/72-lab-capture.rules'
SCRIPT = BASE / 'files/usr/local/sbin/lab-capture-policy'
loader = importlib.machinery.SourceFileLoader('capture_policy37', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
policy = importlib.util.module_from_spec(spec)
loader.exec_module(policy)
REAL_RUN = subprocess.run


def rule_lines(path):
    return [line for line in path.read_text().splitlines() if line and not line.startswith('#')]


class Rules(unittest.TestCase):
    def test_no_microphone_lock(self):
        text = '\n'.join(rule_lines(RULES))
        self.assertNotIn('SUBSYSTEM=="sound"', text)
        self.assertNotIn(':01????:', text)               # raw USB audio devices
        self.assertNotIn('microphone', text)

    def test_camera_lock_unchanged_from_0032(self):
        old = [line for line in rule_lines(OLD_RULES)
               if 'SUBSYSTEM=="sound"' not in line and ':01????:' not in line and 'microphone' not in line]
        self.assertEqual(rule_lines(RULES), old)
        self.assertEqual(sum('video4linux' in line for line in old), 2)
        self.assertEqual(sum(':0e????:' in line or ':06????:' in line for line in old), 2)

    def test_udev_syntax(self):
        result = REAL_RUN(['udevadm', 'verify', str(RULES)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class Policy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'policy'
        self.addCleanup(patch.stopall)
        patch.object(policy, 'POLICY', self.root).start()
        self.run = patch.object(policy.subprocess, 'run').start()
        self.uid = patch.object(policy.os, 'geteuid', return_value=0).start()

    def call(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            policy.main(list(args))
        return out.getvalue()

    def test_status(self):
        self.uid.return_value = 1000
        output = self.call('status')
        self.assertIn('camera: blocked (root only)', output)
        self.assertIn('microphone: not blocked since update 0037', output)
        self.run.assert_not_called()

    def test_microphone_only_explains(self):
        for mode in ('admin', 'off'):
            output = self.call('microphone', mode)
            self.assertIn('not blocked since update 0037', output)
        self.run.assert_not_called()
        self.assertFalse((self.root / 'microphone-admin').exists())

    def test_camera_override_still_works_for_root_only(self):
        self.call('camera', 'admin')
        self.assertTrue((self.root / 'camera-admin').exists())
        self.assertIn('camera: sudo-group accounts only', self.call('status'))
        self.call('camera', 'off')
        self.assertFalse((self.root / 'camera-admin').exists())
        self.uid.return_value = 1001
        with self.assertRaises(SystemExit):
            self.call('camera', 'admin')

    def test_refresh_reloads_and_triggers(self):
        self.call('refresh')
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual(commands[0], ['udevadm', 'control', '--reload-rules'])
        self.assertIn(['udevadm', 'trigger', '--action=change', '--subsystem-match=sound'], commands)


class InstallScript(unittest.TestCase):
    def test_script(self):
        script = (BASE / 'install.sh').read_text()
        self.assertTrue(script.startswith('#!/bin/bash\n'))
        self.assertIn('source "$LAB_UPDATER_HELPERS"', script)
        self.assertIn('files/etc/udev/rules.d/72-lab-capture.rules', script)
        self.assertIn('files/usr/local/sbin/lab-capture-policy', script)
        self.assertIn('lab-capture-policy refresh', script)
        self.assertIn('restart wireplumber pipewire pipewire-pulse', script)
        self.assertNotIn('request_reboot', script)
        self.assertEqual(REAL_RUN(['bash', '-n', str(BASE / 'install.sh')]).returncode, 0)


if __name__ == '__main__':
    unittest.main()
