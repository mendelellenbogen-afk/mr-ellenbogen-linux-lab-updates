#!/usr/bin/env python3
"""0035-bios-lock-script: install.sh in a throwaway namespace (no real files change),
and the shipped copy equals the teacher's tool.

    python3 -I update-repo/tests/test_0035_bios_lock_script.py
"""
import os, subprocess, tempfile, unittest
from pathlib import Path

UPDATE = Path(__file__).resolve().parent.parent / 'updates/0035-bios-lock-script'
HELPERS = Path(__file__).resolve().parents[2] / 'lab-updater/client/usr/local/lib/lab-updater/update-helpers.sh'
TOOL = Path(__file__).resolve().parents[2] / 'tools/lab-bios-lock'

SETUP = r'''
set -e
mount -t tmpfs tmpfs /usr/local
echo 'root:x:0:0:root:/root:/bin/bash' > /tmp/.p; mount -t tmpfs tmpfs /etc
echo 'root:x:0:0:root:/root:/bin/bash' > /etc/passwd; echo 'root:x:0:' > /etc/group
cd "$UPDATE"
bash ./install.sh; bash ./install.sh
stat -c '%a %U' /usr/local/sbin/lab-bios-lock
cmp /usr/local/sbin/lab-bios-lock "$UPDATE/files/lab-bios-lock" && echo SAME
'''


class Installed(unittest.TestCase):
    def test_installs_one_system_copy_and_rerun_is_safe(self):
        env = dict(os.environ, UPDATE=str(UPDATE), LAB_UPDATER_HELPERS=str(HELPERS), LAB_UPDATE_NAME='0035-test')
        r = subprocess.run(['unshare', '-r', '-m', 'bash', '-c', SETUP], env=env, text=True, capture_output=True)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn('755 root', out); self.assertIn('SAME', out)

    def test_shipped_copy_matches_the_tool(self):
        self.assertEqual((UPDATE / 'files/lab-bios-lock').read_bytes(), TOOL.read_bytes())


if __name__ == '__main__':
    unittest.main()
