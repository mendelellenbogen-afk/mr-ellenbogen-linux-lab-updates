#!/usr/bin/env python3
"""Tests for update 0055: memory guard (zram swap, per-program memory limits,
earlier systemd-oomd, the "program closed" pop-up). Fake commands only; no
root needed and nothing on this computer changes.

    python3 -I update-repo/tests/test_0055_memory_guard.py
"""

import configparser
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0055-memory-guard")
FILES = os.path.join(UPDATE, "files")
LIB = os.path.join(FILES, "usr", "local", "lib", "lab-memory")
ZRAM = os.path.join(LIB, "lab-zram")

sys.dont_write_bytecode = True  # no __pycache__ inside the update folder
_loader = importlib.machinery.SourceFileLoader("lab_memory_notice", os.path.join(LIB, "lab-memory-notice"))
_spec = importlib.util.spec_from_loader("lab_memory_notice", _loader)
notice = importlib.util.module_from_spec(_spec)
_loader.exec_module(notice)


def unit_file(*parts):
    config = configparser.ConfigParser(strict=False, interpolation=None)
    config.optionxform = str
    config.read(os.path.join(FILES, *parts))
    return config


def fake_bin(folder, name, script):
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.write("#!/bin/bash\n" + script)
    os.chmod(path, 0o755)


class Settings(unittest.TestCase):

    def test_program_limit(self):
        for folder in ("app-.scope.d", "snap.firefox.firefox-.scope.d"):
            self.assertEqual(unit_file("etc", "systemd", "user", folder, "50-lab-memory.conf")["Scope"]["MemoryHigh"], "60%")

    def test_all_programs_limit(self):
        self.assertEqual(unit_file("etc", "systemd", "user", "app.slice.d", "50-lab-memory.conf")["Slice"]["MemoryHigh"], "80%")

    def test_no_hard_limit(self):
        # Slow down, never kill at the limit: systemd-oomd decides about closing.
        for root, _dirs, names in os.walk(os.path.join(FILES, "etc", "systemd")):
            for name in names:
                with open(os.path.join(root, name)) as f:
                    self.assertNotIn("MemoryMax", f.read())

    def test_oomd_sooner(self):
        service = unit_file("etc", "systemd", "system", "user@.service.d", "50-lab-memory.conf")["Service"]
        self.assertEqual(service["ManagedOOMMemoryPressureDurationSec"], "10s")

    def test_sysctl(self):
        values = {}
        with open(os.path.join(FILES, "etc", "sysctl.d", "90-lab-memory.conf")) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    key, value = (s.strip() for s in line.split("=", 1))
                    values[key] = value
        self.assertEqual(values, {"vm.swappiness": "180", "vm.page-cluster": "0",
                                  "vm.watermark_boost_factor": "0", "vm.watermark_scale_factor": "125"})

    def test_zram_service(self):
        config = unit_file("etc", "systemd", "system", "lab-zram.service")
        self.assertEqual(config["Service"]["ExecStart"], "/usr/local/lib/lab-memory/lab-zram start")
        self.assertEqual(config["Install"]["WantedBy"], "swap.target")

    def test_install_sh_installs_every_file(self):
        with open(os.path.join(UPDATE, "install.sh")) as f:
            install = f.read().replace("files$LIB/", "files/usr/local/lib/lab-memory/")
        for root, _dirs, names in os.walk(FILES):
            for name in names:
                path = os.path.relpath(os.path.join(root, name), FILES)
                if "/systemd/user/" in "/" + path and path.endswith("/50-lab-memory.conf"):
                    self.assertIn(path.split("/")[3], install)  # the loop over the three folders
                else:
                    self.assertIn(path, install)

    def test_executables(self):
        for name in ("lab-zram", "lab-memory-notice"):
            self.assertTrue(os.access(os.path.join(LIB, name), os.X_OK), name)


class Zram(unittest.TestCase):

    def run_zram(self, action, mem_kib=7_900_000, swaps="/swap.img\n", zstd_ok=True):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "log")
            with open(os.path.join(tmp, "meminfo"), "w") as f:
                f.write(f"MemTotal:       {mem_kib} kB\nMemFree:  1000 kB\n")
            for name in ("modprobe", "mkswap", "swapoff"):
                fake_bin(tmp, name, f'echo "{name} $*" >> "{log}"\n')
            fake_bin(tmp, "swapon", f'if [ "$1" = --show=NAME ]; then printf "{swaps}"; exit; fi\necho "swapon $*" >> "{log}"\n')
            fail = "" if zstd_ok else 'case "$*" in *zstd*) exit 1;; esac\n'
            fake_bin(tmp, "zramctl", fail + f'echo "zramctl $*" >> "{log}"\ncase "$1" in --find) echo /dev/zram0;; esac\n')
            env = dict(os.environ, PATH=tmp + ":/usr/bin:/bin", LAB_MEMINFO=os.path.join(tmp, "meminfo"))
            result = subprocess.run(["bash", ZRAM, action], env=env, capture_output=True, text=True)
            calls = open(log).read().splitlines() if os.path.exists(log) else []
            return result, calls

    def test_start(self):
        result, calls = self.run_zram("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["modprobe zram",
                                 "zramctl --find --size 7900000KiB --algorithm zstd",
                                 "mkswap --label lab-zram /dev/zram0",
                                 "swapon --priority 100 /dev/zram0"])

    def test_size_capped_at_8_gib(self):
        _result, calls = self.run_zram("start", mem_kib=32_000_000)
        self.assertIn(f"zramctl --find --size {8 * 1024 * 1024}KiB --algorithm zstd", calls)

    def test_without_zstd(self):
        result, calls = self.run_zram("start", zstd_ok=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("zramctl --find --size 7900000KiB", calls)
        self.assertIn("swapon --priority 100 /dev/zram0", calls)

    def test_already_on(self):
        result, calls = self.run_zram("start", swaps="/swap.img\\n/dev/zram0\\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_stop(self):
        _result, calls = self.run_zram("stop", swaps="/swap.img\\n/dev/zram0\\n")
        self.assertEqual(calls, ["swapoff /dev/zram0", "zramctl --reset /dev/zram0"])

    def test_stop_never_touches_disk_swap(self):
        _result, calls = self.run_zram("stop")
        self.assertEqual(calls, [])


class Notice(unittest.TestCase):

    def test_names(self):
        cases = {
            "app-gnome-intellij-1234.scope": "IntelliJ IDEA",
            "app-com.google.Chrome-386524.scope": "Google Chrome",
            "app-gnome-google\\x2dchrome-12.scope": "Google Chrome",
            "snap.firefox.firefox-3f2a9c1e-11aa-4b2b-9c3d-123456789abc.scope": "Firefox",
            "app-gnome-code-4567.scope": "VS Code",
            "app-gnome-pycharm-77.scope": "PyCharm",
            "app-gnome-org.gnome.Calculator-55.scope": "Calculator",
            "something-else": "A program",
        }
        for unit, name in cases.items():
            self.assertEqual(notice.program_name(unit), name, unit)

    def test_killed_unit(self):
        oomd = {"MESSAGE": "app-gnome-intellij-1234.scope: systemd-oomd killed 12 process(es) in this unit.",
                "USER_UNIT": "app-gnome-intellij-1234.scope"}
        kernel = {"MESSAGE": "x.scope: The kernel OOM killer killed some processes in this unit.", "USER_UNIT": "x.scope"}
        self.assertEqual(notice.killed_unit(oomd), "app-gnome-intellij-1234.scope")
        self.assertEqual(notice.killed_unit(kernel), "x.scope")
        self.assertIsNone(notice.killed_unit({"MESSAGE": "Started app-gnome-intellij-1234.scope.", "USER_UNIT": "y"}))
        self.assertIsNone(notice.killed_unit({"MESSAGE": [1, 2]}))
        self.assertIsNone(notice.killed_unit({}))

    def test_main_pops_up_once_per_program(self):
        lines = [
            {"MESSAGE": "Started app-gnome-intellij-1234.scope.", "USER_UNIT": "app-gnome-intellij-1234.scope"},
            {"MESSAGE": "app-com.google.Chrome-9.scope: systemd-oomd killed 40 process(es) in this unit.",
             "USER_UNIT": "app-com.google.Chrome-9.scope"},
            {"MESSAGE": "app-com.google.Chrome-9.scope: The kernel OOM killer killed some processes in this unit.",
             "USER_UNIT": "app-com.google.Chrome-9.scope"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "journal"), "w") as f:
                f.write("".join(json.dumps(line) + "\n" for line in lines) + "not json\n")
            log = os.path.join(tmp, "log")
            fake_bin(tmp, "journalctl", f'echo "journalctl $*" >> "{log}"\ncat "{tmp}/journal"\n')
            fake_bin(tmp, "notify-send", f'printf "notify-send %s\\n" "$*" >> "{log}"\n')
            env = dict(os.environ, PATH=tmp + ":/usr/bin:/bin")
            result = subprocess.run(["python3", "-I", os.path.join(LIB, "lab-memory-notice")],
                                    env=env, capture_output=True, text=True, timeout=20)
            calls = open(log).read().splitlines()
        self.assertEqual(result.returncode, 1)  # journal ended: systemd restarts it
        self.assertEqual(calls[0], "journalctl --user --follow --lines=0 --output=json")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].startswith("notify-send --urgency=critical"))
        self.assertIn("Google Chrome was using too much memory", calls[1])

    def test_user_service(self):
        config = unit_file("etc", "systemd", "user", "lab-memory-notice.service")
        self.assertEqual(config["Unit"]["ConditionUser"], "!@system")
        self.assertTrue(re.search(r"lab-memory-notice$", config["Service"]["ExecStart"]))
        self.assertEqual(config["Install"]["WantedBy"], "default.target")


if __name__ == "__main__":
    unittest.main()
