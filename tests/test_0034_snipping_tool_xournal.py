#!/usr/bin/env python3
"""0034-snipping-tool-xournal-settings: install.sh in a throwaway namespace with fake
system tools (no real apt, snap, dconf or files change), plus checks of the shipped
Xournal++ settings and the lab-snip script.

    python3 -I update-repo/tests/test_0034_snipping_tool_xournal.py
"""
import os, py_compile, subprocess, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

UPDATE = Path(__file__).resolve().parent.parent / 'updates/0034-snipping-tool-xournal-settings'
HELPERS = Path(__file__).resolve().parents[2] / 'lab-updater/client/usr/local/lib/lab-updater/update-helpers.sh'

SETUP = r'''
set -e
cp -rP /etc/alternatives "$TEST_ROOT/alt"
for d in /usr/local /etc; do mount -t tmpfs tmpfs $d; done
cp -rP "$TEST_ROOT/alt" /etc/alternatives
echo 'root:x:0:0:root:/root:/bin/bash' > /etc/passwd; echo 'root:x:0:' > /etc/group
mkdir -p /usr/local/share/applications
H="$TEST_ROOT/home"; mkdir -p "$H/admin/snap/xournalpp/200/.config/xournalpp" "$H/stu"
ln -s 200 "$H/admin/snap/xournalpp/current"
echo '<old settings/>' > "$H/admin/snap/xournalpp/current/.config/xournalpp/settings.xml"
cd "$UPDATE"
set +e
bash ./install.sh; echo "rc=$?"
'''

class Snipping(unittest.TestCase):
    def run_it(self, xournal='snap', busy=False, setup=SETUP):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); bindir = root / 'bin'; bindir.mkdir()
        self.log = root / 'calls'; self.log.touch(); self.root = root
        def stub(name, body):
            p = bindir / name; p.write_text('#!/bin/bash\n' + body + '\n'); p.chmod(0o755)
        for n in ('apt-get', 'dconf', 'update-desktop-database'):
            stub(n, f'echo "{n} $*" >> "{self.log}"')
        stub('snap', 'if [ "$1" = list ] && [ "$2" = xournalpp ]; then ' +
             ('printf "Name Version Rev\\nxournalpp 1.3.8 200\\n"; exit 0; fi; exit 1' if xournal == 'snap' else 'exit 1; fi; exit 1'))
        stub('dpkg-query', 'exit 1')
        stub('getent', f'case "$1" in group) echo "sudo:x:27:admin";; passwd) echo "admin:x:1000:1000::{root}/home/admin:/bin/bash";; esac')
        stub('runuser', 'shift 3; exec "$@"')
        stub('pgrep', 'exit ' + ('0' if busy else '1'))
        env = dict(os.environ, PATH=f'{bindir}:{os.environ["PATH"]}', TEST_ROOT=str(root),
                   UPDATE=str(UPDATE), LAB_UPDATER_HELPERS=str(HELPERS), LAB_UPDATE_NAME='0034-test')
        r = subprocess.run(['unshare', '-r', '-m', 'bash', '-c', setup + CHECKS], env=env, text=True, capture_output=True)
        return r.stdout + r.stderr, self.log.read_text()

    def test_installs_snip_tool_and_refreshes_xournal(self):
        out, calls = self.run_it()
        self.assertIn('rc=0', out, out); self.assertIn('SNIP_FILES_OK', out, out)
        self.assertIn('XOURNAL_OK', out, out); self.assertIn('BACKUP_OK', out, out)
        self.assertNotIn('WRONG', out)
        self.assertIn('apt-get -o DPkg::Lock::Timeout=900 update', calls)
        self.assertIn('install -y --no-install-recommends swappy wl-clipboard libnotify-bin', calls)
        self.assertIn('dconf update', calls)

    def test_rerun_is_safe(self):
        out, _ = self.run_it(setup=SETUP.replace('bash ./install.sh; echo "rc=$?"', 'bash ./install.sh; bash ./install.sh; echo "rc=$?"'))
        self.assertIn('rc=0', out, out)

    def test_open_xournal_waits_but_snip_tool_is_done(self):
        out, _ = self.run_it(busy=True)
        self.assertNotIn('rc=0', out); self.assertIn('SNIP_FILES_OK', out, out)
        self.assertIn('NO_XOURNAL_WRITE', out, out)

    def test_no_xournal_installed_is_fine(self):
        out, _ = self.run_it(xournal='none')
        self.assertIn('rc=0', out, out); self.assertIn('SNIP_FILES_OK', out, out)


CHECKS = r'''
[ -x /usr/local/bin/lab-snip ] && [ -f /usr/local/share/applications/lab-snip.desktop ] \
  && grep -q "binding='<Shift><Super>s'" /etc/dconf/db/local.d/50-lab-snip \
  && grep -qx 'system-db:local' /etc/dconf/profile/user && echo SNIP_FILES_OK
S="$TEST_ROOT/home/admin/snap/xournalpp/current/.config/xournalpp/settings.xml"
if grep -q 'buttonConfig' "$S" 2>/dev/null; then
    ! grep -q '/home/' "$S" && echo XOURNAL_OK
    [ -f "$S.before-0034" ] && grep -q old "$S.before-0034" && echo BACKUP_OK
else
    grep -q '<old settings/>' "$S" && echo NO_XOURNAL_WRITE
fi
'''


class Shipped(unittest.TestCase):
    def test_settings_pen_buttons_and_no_private_paths(self):
        text = (UPDATE / 'files/settings.xml').read_text()
        self.assertNotIn('/home/', text); self.assertNotIn('mendel', text.lower())
        cfg = {d.get('name'): {a.get('name'): a.get('value') for a in d.findall('attribute')}
               for d in ET.fromstring(text).find("data[@name='buttonConfig']").findall('data')}
        self.assertEqual((cfg['stylus']['tool'], cfg['stylus']['eraserMode']), ('eraser', 'deleteStroke'))
        self.assertEqual(cfg['stylus2']['tool'], 'selectRegion')
        self.assertEqual(cfg['eraser']['tool'], 'eraser')

    def test_lab_snip_compiles_and_has_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(UPDATE / 'files/usr/local/bin/lab-snip'), cfile=os.path.join(tmp, 'x.pyc'), doraise=True)
        self.assertIn('"interactive"', (UPDATE / 'files/usr/local/bin/lab-snip').read_text())


if __name__ == '__main__':
    unittest.main()
