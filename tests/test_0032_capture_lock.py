#!/usr/bin/env python3
"""Policy safety checks and root CLI behavior without touching host devices."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / 'updates/0032-capture-lock'
FILES = BASE / 'files'
SCRIPT = FILES / 'usr/local/sbin/lab-capture-policy'
loader = importlib.machinery.SourceFileLoader('capture_policy', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
policy = importlib.util.module_from_spec(spec)
loader.exec_module(policy)

class CapturePolicyTests(unittest.TestCase):
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

    def test_default_and_unprivileged_status(self):
        self.uid.return_value = 1000
        output = self.call('status')
        self.assertEqual(output.count('blocked (root only)'), 2)
        self.run.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_student_cannot_enable_or_refresh(self):
        self.uid.return_value = 1001
        for args in [('camera', 'admin'), ('microphone', 'admin'), ('refresh',)]:
            with self.assertRaises(SystemExit):
                self.call(*args)
        self.run.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_independent_override_and_relock(self):
        self.call('camera', 'admin')
        self.assertTrue((self.root / 'camera-admin').exists())
        self.assertFalse((self.root / 'microphone-admin').exists())
        self.call('microphone', 'admin')
        self.call('camera', 'off')
        self.assertFalse((self.root / 'camera-admin').exists())
        self.assertTrue((self.root / 'microphone-admin').exists())
        self.call('camera', 'off')
        self.call('refresh')
        self.assertTrue((self.root / 'microphone-admin').exists())

    def test_invalid_arguments_cannot_mutate(self):
        for args in [('camera',), ('status', 'admin'), ('refresh', 'off'), ('all', 'admin')]:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.call(*args)
        self.run.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_refresh_failure_is_not_success(self):
        self.run.side_effect = subprocess.CalledProcessError(1, 'udevadm')
        with self.assertRaises(subprocess.CalledProcessError):
            self.call('camera', 'off')

    def test_refresh_covers_hotplug_subsystems_without_bluetooth_changes(self):
        self.call('refresh')
        calls = [c.args[0] for c in self.run.call_args_list]
        self.assertEqual(calls[0], ['udevadm', 'control', '--reload-rules'])
        self.assertEqual(calls[-1], ['udevadm', 'settle', '--timeout=30'])
        self.assertEqual({c[-1] for c in calls[1:-1]}, {
            '--subsystem-match='+s for s in ('video4linux', 'media', 'sound', 'usb')})
        self.assertTrue(all(c.kwargs.get('check') for c in self.run.call_args_list))

    def test_rules_remove_acl_and_finalize_permissions(self):
        rules = (FILES / 'etc/udev/rules.d/72-lab-capture.rules').read_text()
        for line in rules.splitlines():
            if 'MODE:=' in line:
                self.assertIn('TAG-="uaccess"', line)
                self.assertIn('OWNER:="root"', line)
                self.assertIn('ENV{LAB_CAPTURE_LOCK}="1"', line)
                if '0660' in line:
                    self.assertIn('GROUP:="sudo"', line)
                    self.assertIn('TEST=="/etc/lab-capture/', line)
                else:
                    self.assertIn('GROUP:="root", MODE:="0600"', line)
        self.assertIn('KERNEL=="pcmC*D*c"', rules)
        self.assertNotIn('KERNEL=="pcmC*D*p"', rules)
        for cls in ('0e', '01', '06'):
            self.assertIn('*:'+cls+'????:*', rules)
        late = (FILES / 'etc/udev/rules.d/99-lab-capture-acl.rules').read_text()
        self.assertIn('ENV{LAB_CAPTURE_LOCK}=="1"', late)
        self.assertIn('/usr/bin/setfacl -b $devnode', late)

    def test_acl_cleanup_removes_existing_student_grant(self):
        import os
        import stat
        node = Path(self.tmp.name) / 'synthetic-device'
        node.touch()
        REAL_RUN(['setfacl', '-m', 'u:42424:rw', str(node)], check=True)
        for mode in ('0600', '0660'):
            REAL_RUN(['setfacl', '-b', str(node)], check=True)
            REAL_RUN(['chmod', mode, str(node)], check=True)
            acl = REAL_RUN(['getfacl', '-cp', str(node)], capture_output=True,
                           text=True, check=True).stdout
            self.assertNotIn('42424', acl)
            self.assertEqual(stat.S_IMODE(os.stat(node).st_mode), int(mode, 8))

    def test_udev_syntax(self):
        # use original run function: the policy module shares subprocess globally
        for path in (FILES / 'etc/udev/rules.d').glob('*.rules'):
            result = REAL_RUN(['udevadm', 'verify', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

REAL_RUN = subprocess.run
if __name__ == '__main__':
    unittest.main()
