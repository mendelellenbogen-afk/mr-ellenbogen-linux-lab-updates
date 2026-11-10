#!/usr/bin/env python3
"""0058-snipping-tool-v2: install.sh in a throwaway namespace with fake system tools
(no real apt, dconf or files change), the add-on's geometry (gjs), the lab-snip
launcher (--edit with a fake editor) and the shipped patched Swappy.

    python3 -I update-repo/tests/test_0058_snipping_tool_v2.py

The overlay itself was tried in a headless GNOME Shell 50.1 session (see SESSION-LOG).
"""
import importlib.machinery, importlib.util, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPDATE = HERE.parent / 'updates/0058-snipping-tool-v2'
HELPERS = HERE.parents[1] / 'lab-updater/client/usr/local/lib/lab-updater/update-helpers.sh'
EXT = UPDATE / 'files/usr/share/gnome-shell/extensions/lab-snip@school.local'
LAB_SNIP = UPDATE / 'files/usr/local/bin/lab-snip'
SWAPPY = UPDATE / 'files/usr/local/lib/lab-snip/swappy'

SETUP = r'''
set -e
cp -rP /etc/alternatives "$TEST_ROOT/alt"
for d in /usr/local /etc /usr/share/gnome-shell; do mount -t tmpfs tmpfs $d; done
cp -rP "$TEST_ROOT/alt" /etc/alternatives
echo 'root:x:0:0:root:/root:/bin/bash' > /etc/passwd; echo 'root:x:0:' > /etc/group
cd "$UPDATE"
set +e
bash ./install.sh; echo "rc=$?"
'''

CHECKS = r'''
E=/usr/share/gnome-shell/extensions/lab-snip@school.local
[ -x /usr/local/bin/lab-snip ] && [ -x /usr/local/lib/lab-snip/swappy ] \
  && [ -f $E/metadata.json ] && [ -f $E/extension.js ] && [ -f $E/geometry.js ] \
  && [ "$(stat -c %a $E/extension.js)" = 644 ] && [ "$(stat -c %a /usr/local/lib/lab-snip/swappy)" = 755 ] \
  && grep -q "enabled-extensions=\['lab-snip@school.local'\]" /etc/dconf/db/local.d/50-lab-snip-extension \
  && grep -qx 'system-db:local' /etc/dconf/profile/user && echo FILES_OK
[ "$(grep -c 'system-db:local' /etc/dconf/profile/user)" = 1 ] && echo PROFILE_ONCE
'''


class Install(unittest.TestCase):
    def run_it(self, setup=SETUP):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); bindir = root / 'bin'; bindir.mkdir()
        log = root / 'calls'; log.touch()
        for n in ('apt-get', 'dconf'):
            p = bindir / n; p.write_text(f'#!/bin/bash\necho "{n} $*" >> "{log}"\n'); p.chmod(0o755)
        env = dict(os.environ, PATH=f'{bindir}:{os.environ["PATH"]}', TEST_ROOT=str(root),
                   UPDATE=str(UPDATE), LAB_UPDATER_HELPERS=str(HELPERS), LAB_UPDATE_NAME='0058-test')
        r = subprocess.run(['unshare', '-r', '-m', 'bash', '-c', setup + CHECKS], env=env, text=True, capture_output=True)
        return r.stdout + r.stderr, log.read_text()

    def test_installs_everything(self):
        out, calls = self.run_it()
        self.assertIn('rc=0', out, out); self.assertIn('FILES_OK', out, out)
        self.assertIn('install -y --no-install-recommends swappy wl-clipboard libnotify-bin', calls)
        self.assertIn('dconf update', calls)

    def test_rerun_is_safe(self):
        out, _ = self.run_it(SETUP.replace('bash ./install.sh; echo', 'bash ./install.sh; bash ./install.sh; echo'))
        self.assertIn('rc=0', out, out); self.assertIn('FILES_OK', out, out); self.assertIn('PROFILE_ONCE', out, out)


class AddOn(unittest.TestCase):
    def test_metadata(self):
        meta = json.loads((EXT / 'metadata.json').read_text())
        self.assertEqual(meta['uuid'], 'lab-snip@school.local')
        self.assertEqual(meta['shell-version'], ['50'])
        self.assertNotIn('gdm', meta.get('session-modes', ['user']))   # never on the login screen

    def test_launches_lab_snip_and_exports_start(self):
        js = (EXT / 'extension.js').read_text()
        self.assertIn("'/usr/local/bin/lab-snip', '--edit'", js)
        self.assertIn("'/org/school/LabSnip'", js)
        self.assertIn('org.school.LabSnip', js)
        self.assertNotIn('Meta.Cursor', js)        # removed in GNOME 50 (broke the first draft)

    @unittest.skipUnless(shutil.which('gjs'), 'gjs not installed')
    def test_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(EXT / 'geometry.js', tmp)
            shutil.copy(HERE / 'test_0058_geometry.js', Path(tmp) / 'test.js')
            r = subprocess.run(['gjs', '-m', 'test.js'], cwd=tmp, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('FAIL', r.stdout)
        self.assertGreaterEqual(r.stdout.count('PASS'), 13, r.stdout)


def load_lab_snip():
    loader = importlib.machinery.SourceFileLoader('lab_snip', str(LAB_SNIP))
    spec = importlib.util.spec_from_loader('lab_snip', loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    return module


class Launcher(unittest.TestCase):
    def test_edit_opens_editor_with_config_and_deletes_picture(self):
        snip = load_lab_snip()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); seen = tmp / 'seen'
            fake = tmp / 'swappy'
            fake.write_text('#!/bin/bash\n{ echo "ARGS $*"; echo "NEW $SWAPPY_NEW_COMMAND"; '
                            f'cat "$XDG_CONFIG_HOME/swappy/config"; }} > "{seen}"\n')
            fake.chmod(0o755)
            picture = tmp / 'snip.png'; picture.write_bytes(b'png')
            snip.SWAPPY = str(fake)
            os.environ['HOME'] = str(tmp)
            self.assertEqual(snip.main(['--edit', str(picture)]), 0)
            text = seen.read_text()
        self.assertFalse(picture.exists())
        self.assertIn(f'ARGS -f {picture}', text)
        self.assertIn('NEW /usr/local/bin/lab-snip', text)
        self.assertIn(f'save_dir={tmp}/Pictures/Screenshots', text)   # no Pictures folder set up: not $HOME
        for line in ('save_filename_format=swappy-%Y%m%d-%H%M%S.png', 'show_panel=false', 'line_size=5',
                     'text_size=20', 'paint_mode=brush', 'early_exit=false'):
            self.assertIn(line, text)

    def test_bad_arguments(self):
        self.assertEqual(load_lab_snip().main(['--nope']), 2)


class Editor(unittest.TestCase):
    def test_patched_swappy_runs_and_has_the_lab_changes(self):
        r = subprocess.run([str(SWAPPY), '--version'], text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('1.5.1', r.stdout + r.stderr)
        data = SWAPPY.read_bytes()
        for marker in (b'New Screenshot (closes this window)', b'/usr/local/bin/lab-snip',
                       b'SWAPPY_NEW_COMMAND', b'show_close_button'):
            self.assertIn(marker, data)

    def test_patch_and_build_script_ship_with_it(self):
        patch = (UPDATE / 'swappy/0001-lab-new-button-autocopy-rightclick.patch').read_text()
        for marker in ('new_clicked_handler', 'clipboard_copy_original_image', 'event->button == 3',
                       'show_close_button'):
            self.assertIn(marker, patch)
        self.assertIn('v1.5.1', (UPDATE / 'swappy/build.sh').read_text())


if __name__ == '__main__':
    unittest.main()
