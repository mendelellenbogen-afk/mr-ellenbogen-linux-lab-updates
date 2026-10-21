#!/usr/bin/env python3
"""0033-remove-rustdesk: run install.sh in a throwaway namespace with fake system tools.
Nothing on this computer changes (no real apt, systemctl or files).

    python3 -I update-repo/tests/test_0033_remove_rustdesk.py
"""
import os, subprocess, tempfile, unittest
from pathlib import Path

UPDATE = Path(__file__).resolve().parent.parent / 'updates/0033-remove-rustdesk'
HELPERS = Path(__file__).resolve().parents[2] / 'lab-updater/client/usr/local/lib/lab-updater/update-helpers.sh'

SETUP = r'''
set -e
for d in /usr/local /etc /usr/lib/systemd; do mount -t tmpfs tmpfs $d; done
mkdir -p /usr/local/bin /usr/local/lib/lab-rustdesk /usr/local/share/applications \
         /etc/xdg/autostart /etc/systemd/system /usr/lib/systemd/user
touch /usr/local/bin/lab-rustdesk /usr/local/lib/lab-rustdesk/admin-menu \
      /usr/local/share/applications/rustdesk.desktop /usr/local/share/applications/rustdesk-link.desktop \
      /etc/xdg/autostart/lab-rustdesk-menu.desktop /etc/systemd/system/rustdesk.service
touch /usr/local/bin/lab-ai-desktop /etc/xdg/autostart/lab-ai-desktop-menu.desktop   # must survive
H="$TEST_ROOT/home"; mkdir -p "$H/admin/.local/share/applications" "$H/stu/.local/share/applications"
printf '[Desktop Entry]\nX-Lab-RustDesk-Menu=true\n' > "$H/admin/.local/share/applications/rustdesk.desktop"
printf '[Desktop Entry]\nName=Mine\n' > "$H/stu/.local/share/applications/rustdesk.desktop"
bash "$UPDATE/install.sh"; echo "rc=$?"
bash "$UPDATE/install.sh"; echo "rerun rc=$?"
for f in /usr/local/bin/lab-rustdesk /usr/local/lib/lab-rustdesk /etc/xdg/autostart/lab-rustdesk-menu.desktop \
         /etc/systemd/system/rustdesk.service /usr/local/share/applications/rustdesk.desktop; do
    [ ! -e "$f" ] || echo "STILL THERE $f"; done
for f in /usr/local/bin/lab-ai-desktop /etc/xdg/autostart/lab-ai-desktop-menu.desktop "$H/stu/.local/share/applications/rustdesk.desktop"; do
    [ -e "$f" ] || echo "WRONGLY REMOVED $f"; done
[ ! -e "$H/admin/.local/share/applications/rustdesk.desktop" ] || echo "STILL THERE admin entry"
'''

class RemoveRustDesk(unittest.TestCase):
    def run_it(self, installed):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); bindir = root / 'bin'; bindir.mkdir()
        log = root / 'calls'; log.touch()
        def stub(name, body):
            p = bindir / name; p.write_text('#!/bin/bash\n' + body + '\n'); p.chmod(0o755)
        for n in ('systemctl', 'pkill', 'apt-get'):
            stub(n, f'echo "{n} $*" >> "{log}"')
        stub('dpkg-query', 'case "$3" in rustdesk-unattended-wayland) ' +
             ('echo "install ok installed"' if installed else 'exit 1') + ';; *) exit 1;; esac')
        stub('getent', f'echo "admin:x:1000:1000::{root}/home/admin:/bin/bash"; '
                       f'echo "stu:x:1001:1001::{root}/home/stu:/bin/bash"; echo "root:x:0:0::/root:/bin/bash"')
        env = dict(os.environ, PATH=f'{bindir}:{os.environ["PATH"]}', TEST_ROOT=str(root),
                   UPDATE=str(UPDATE), LAB_UPDATER_HELPERS=str(HELPERS), LAB_UPDATE_NAME='0033-test')
        r = subprocess.run(['unshare', '-r', '-m', 'bash', '-c', SETUP], env=env, text=True, capture_output=True)
        return r, log.read_text()

    def test_removes_rustdesk_and_keeps_the_rest(self):
        r, calls = self.run_it(installed=True)
        out = r.stdout + r.stderr
        self.assertIn('rc=0', out); self.assertIn('rerun rc=0', out, out)
        self.assertNotIn('STILL THERE', out); self.assertNotIn('WRONGLY REMOVED', out)
        self.assertIn('apt-get -o DPkg::Lock::Timeout=900 purge -y rustdesk-unattended-wayland', calls)
        self.assertIn('systemctl disable --now rustdesk.service', calls)

    def test_nothing_installed_is_harmless(self):
        r, calls = self.run_it(installed=False)
        self.assertIn('rerun rc=0', r.stdout + r.stderr)
        self.assertNotIn('apt-get', calls)

if __name__ == '__main__':
    unittest.main()
