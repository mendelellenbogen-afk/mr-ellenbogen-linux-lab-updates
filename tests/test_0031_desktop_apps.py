#!/usr/bin/env python3
"""Exercise package integrity/idempotency and admin menu behavior with fakes.
No real installation, remote connection, credentials or student data.
"""
import hashlib
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

UPDATE = Path(__file__).resolve().parent.parent / 'updates/0031-desktop-apps'
FILES = UPDATE / 'files'
PACKAGE = 'rustdesk-unattended-wayland-1.5.0-x86_64.deb'
SHA = '9eed5e9f4b47af8ed41585c399cb2c0d2870e801c99645330dea1063ad844e09'


class RustDesk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.home = self.root / 'admin home'
        self.home.mkdir()
        self.log = self.root / 'calls'
        self.env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                        TEST_HOME=str(self.home), TEST_LOG=str(self.log),
                        TEST_ROOT=str(self.root), TEST_GROUPS='sudo users',
                        LAB_UPDATE_NAME='0031-test')
        self.stub('id', 'if [ "$1" = -u ]; then echo 1000; else echo "$TEST_GROUPS"; fi')
        self.stub('getent', 'echo "admin:x:1000:1000:Test:$TEST_HOME:/bin/bash"')

    def stub(self, name, body):
        p = self.bin / name
        p.write_text('#!/bin/bash\nset -e\n' + body + '\n')
        p.chmod(0o755)

    def run_script(self, path, **env):
        return subprocess.run(['bash', str(path)], env=dict(self.env, **env),
                              text=True, capture_output=True, cwd=UPDATE)

    def menu_script(self):
        p = self.root / 'admin-menu'
        src = FILES / 'usr/local/lib/lab-rustdesk/rustdesk.desktop'
        p.write_text((FILES / 'usr/local/lib/lab-rustdesk/admin-menu').read_text()
                     .replace('/usr/local/lib/lab-rustdesk/rustdesk.desktop', shlex.quote(str(src))))
        return p

    def test_admin_menu_and_demotion(self):
        p = self.menu_script()
        target = self.home / '.local/share/applications/rustdesk.desktop'
        for _ in range(2):
            self.assertEqual(self.run_script(p).returncode, 0)
        self.assertIn('X-Lab-RustDesk-Menu=true', target.read_text())
        self.assertEqual(self.run_script(p, TEST_GROUPS='users').returncode, 0)
        self.assertFalse(target.exists())

    def test_student_menu_does_not_delete_unrelated_launcher(self):
        target = self.home / '.local/share/applications/rustdesk.desktop'
        target.parent.mkdir(parents=True)
        target.write_text('[Desktop Entry]\nName=Personal launcher\n')
        self.assertEqual(self.run_script(self.menu_script(), TEST_GROUPS='users').returncode, 0)
        self.assertIn('Personal launcher', target.read_text())

    def test_student_cannot_use_lab_launcher(self):
        result = self.run_script(FILES / 'usr/local/bin/lab-rustdesk', TEST_GROUPS='users')
        self.assertEqual(result.returncode, 1)
        self.assertIn('administrator', result.stderr)

    def test_launch_preserves_arguments(self):
        self.stub('fake-rustdesk', 'printf "%s\\n" "$@"')
        p = self.root / 'launcher'
        p.write_text((FILES / 'usr/local/bin/lab-rustdesk').read_text()
                     .replace('/usr/bin/rustdesk', str(self.bin / 'fake-rustdesk')))
        result = subprocess.run(['bash', str(p), 'argument with spaces', '--example'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines(), ['argument with spaces', '--example'])

    def installer_fakes(self):
        self.stub('dpkg', 'echo "${TEST_ARCH:-amd64}"')
        self.stub('dpkg-query', '''if [ "${@: -1}" = google-chrome-stable ]; then
printf "%s" "${TEST_CHROME_INSTALLED:-not installed}"
else
case "${@: -1}" in
chatgpt|claude-desktop) printf "%s" "${TEST_AI_INSTALLED:-not installed}" ;;
*) printf "%s" "${TEST_INSTALLED:-not installed}" ;;
esac
fi''')
        for name in ['apt-get', 'systemctl', 'runuser', 'chmod', 'chown']:
            self.stub(name, f'echo "{name} $*" >> "$TEST_LOG"')
        self.stub('dpkg-statoverride', '''if [ "$1" = --list ]; then
test -f "$TEST_ROOT/overrides" || exit 1
awk -v path="$2" '$4 == path {print}' "$TEST_ROOT/overrides"
else
echo "$2 $3 ${4#0} $5" >> "$TEST_ROOT/overrides"
echo "dpkg-statoverride $*" >> "$TEST_LOG"
fi''')
        helper = self.root / 'helpers.sh'
        helper.write_text('''set -euo pipefail
say() { echo "$*"; }
install_file() { install -Dm"${3:-644}" "$1" "$TEST_ROOT$2"; }
apt_install() { apt-get install "$@"; }
''')
        self.env['LAB_UPDATER_HELPERS'] = str(helper)

    def test_installer_first_run_then_rerun(self):
        self.installer_fakes()
        result = self.run_script(UPDATE / 'install.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        first = self.log.read_text()
        self.assertIn('apt-get install', first)
        self.assertIn('google-chrome-stable', first)
        self.assertIn('runuser -u admin', first)
        self.assertIn('systemctl enable --now rustdesk.service', first)
        self.log.write_text('')
        result = self.run_script(UPDATE / 'install.sh',
                                 TEST_INSTALLED='install ok installed 1.5.0',
                                 TEST_CHROME_INSTALLED='install ok installed',
                                 TEST_AI_INSTALLED='install ok installed')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('apt-get', self.log.read_text())
        desktop = self.root / 'usr/local/share/applications/rustdesk.desktop'
        self.assertIn('NoDisplay=true', desktop.read_text())
        self.assertTrue((self.root / 'etc/xdg/autostart/lab-rustdesk-menu.desktop').exists())

    def test_chrome_installs_even_when_rustdesk_already_present(self):
        self.installer_fakes()
        result = self.run_script(UPDATE / 'install.sh',
                                 TEST_INSTALLED='install ok installed 1.5.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apt-get install google-chrome-stable chatgpt claude-desktop', self.log.read_text())
        source = self.root / 'etc/apt/sources.list.d/google-chrome.list'
        self.assertIn('signed-by=/usr/share/keyrings/lab-google-chrome.gpg', source.read_text())
        self.assertTrue((self.root / 'usr/share/keyrings/lab-google-chrome.gpg').exists())

    def test_existing_chrome_is_not_reinstalled(self):
        self.installer_fakes()
        result = self.run_script(UPDATE / 'install.sh',
                                 TEST_CHROME_INSTALLED='install ok installed')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('google-chrome-stable', self.log.read_text())

    def test_google_key_matches_official_primary_fingerprint(self):
        result = subprocess.check_output(['gpg', '--show-keys', '--with-colons',
            str(FILES / 'usr/share/keyrings/lab-google-chrome.gpg')], text=True)
        first = next(l.split(':')[9] for l in result.splitlines() if l.startswith('fpr:'))
        self.assertEqual(first, 'EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796')

    def test_wrong_architecture_stops_before_install(self):
        self.installer_fakes()
        result = self.run_script(UPDATE / 'install.sh', TEST_ARCH='arm64')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_tampered_package_stops_before_install(self):
        self.installer_fakes()
        update = self.root / 'tampered'
        (update / 'packages').mkdir(parents=True)
        (update / 'packages' / PACKAGE).write_bytes(b'not the release')
        shutil.copy(UPDATE / 'install.sh', update)
        result = subprocess.run(['bash', str(update / 'install.sh')], cwd=update,
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_bundled_package_matches_official_release(self):
        self.assertEqual(hashlib.sha256((UPDATE / 'packages' / PACKAGE).read_bytes()).hexdigest(), SHA)
        result = subprocess.check_output(['dpkg-deb', '--field',
            str(UPDATE / 'packages' / PACKAGE), 'Package', 'Version', 'Architecture'], text=True)
        self.assertIn('rustdesk-unattended-wayland', result)
        self.assertIn('1.5.0', result)
        self.assertIn('amd64', result)

    def test_ai_permissions_persist_and_conflicts_stop_install(self):
        self.installer_fakes()
        result = self.run_script(UPDATE / 'install.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        overrides = (self.root / 'overrides').read_text()
        self.assertIn('root sudo 750 /usr/lib/chatgpt', overrides)
        self.assertIn('root sudo 750 /usr/lib/claude-desktop', overrides)
        self.assertIn('chmod 0750 /usr/lib/chatgpt', self.log.read_text())
        self.assertIn('chown root:sudo /usr/lib/claude-desktop', self.log.read_text())
        self.log.write_text('')
        result = self.run_script(UPDATE / 'install.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('dpkg-statoverride --add', self.log.read_text())
        (self.root / 'overrides').write_text('root root 755 /usr/lib/chatgpt\n')
        self.log.write_text('')
        result = self.run_script(UPDATE / 'install.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflicting permission override', result.stdout)
        self.assertNotIn('apt-get', self.log.read_text())

    def test_ai_menu_admin_demotion_and_student_launcher(self):
        script = self.root / 'ai-menu'
        script.write_text((FILES / 'usr/local/lib/lab-ai-desktop/admin-menu').read_text()
            .replace('/usr/local/lib/lab-ai-desktop', str(FILES / 'usr/local/lib/lab-ai-desktop')))
        self.assertEqual(self.run_script(script).returncode, 0)
        for name in ['chatgpt.desktop', 'com.anthropic.Claude.desktop']:
            target = self.home / '.local/share/applications' / name
            self.assertIn('X-Lab-AI-Desktop-Menu=true', target.read_text())
        self.assertEqual(self.run_script(script, TEST_GROUPS='users').returncode, 0)
        self.assertFalse((self.home / '.local/share/applications/chatgpt.desktop').exists())
        self.assertFalse((self.home / '.local/share/applications/com.anthropic.Claude.desktop').exists())
        result = self.run_script(FILES / 'usr/local/bin/lab-ai-desktop', TEST_GROUPS='users')
        self.assertEqual(result.returncode, 1)
        self.assertIn('administrator', result.stderr)

    def test_ai_launcher_rejects_unknown_program(self):
        result = subprocess.run(['bash', str(FILES / 'usr/local/bin/lab-ai-desktop'), 'bash'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Unknown desktop app', result.stderr)

    def test_ai_repository_keys_match_vendor_fingerprints(self):
        for key, expected in [
            ('chatgpt-archive-keyring.gpg', '3BFA0E4AE8B8CC16A2D9BA684A3B4A566C4660E4'),
            ('claude-desktop-archive-keyring.asc', '31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE')]:
            result = subprocess.check_output(['gpg', '--show-keys', '--with-colons',
                str(FILES / 'usr/share/keyrings' / key)], text=True)
            actual = next(l.split(':')[9] for l in result.splitlines() if l.startswith('fpr:'))
            self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
