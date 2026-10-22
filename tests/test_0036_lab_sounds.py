#!/usr/bin/env python3
"""Tests for 0036-lab-sounds: lab-sound itself (fake player and wpctl), the
listener's "sound" messages, the quiz agent's end countdown, and the quiz
window's sounds and countdown bar (private Broadway display, a made-up quiz).
Every older listener test (0008-0025) and quiz test (0028, 0030) reruns on
the new files. No network, no root, nothing is played.

    python3 -I update-repo/tests/test_0036_lab_sounds.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0036-lab-sounds")
FILES = os.path.join(UPDATE, "files")
LISTENER = os.path.join(FILES, "usr", "local", "lib", "lab-messages", "lab-messages-listener.py")
AGENT = os.path.join(FILES, "usr", "local", "lib", "lab-quiz", "lab-quiz-agent.py")
WINDOW = os.path.join(FILES, "usr", "local", "lib", "lab-quiz", "quiz-window.py")
LAB_SOUND = os.path.join(FILES, "usr", "local", "bin", "lab-sound")
SOUNDS = os.path.join(FILES, "usr", "local", "share", "lab-sounds")

sys.path.insert(0, HERE)
import test_0008_live_messages as t8   # noqa: E402
import test_0019_admin_only_messages as t19   # noqa: E402
import test_0020_open_links as t20   # noqa: E402
import test_0021_fullscreen_links as t21   # noqa: E402
import test_0023_targeted_messages as t23   # noqa: E402
import test_0024_class_polls as t24   # noqa: E402
import test_0025_poll_correct_answers as t25   # noqa: E402
import test_0028_quiz_improvements_power as t28   # noqa: E402
import test_0030_quiz_choices_input as t30   # noqa: E402

listener = t19.load("listener36", LISTENER)
for module in (t8, t19, t20, t21, t23, t24, t25):
    module.listener = listener
t24.WINDOW = t25.WINDOW                 # the poll window is unchanged since 0025
t28.AGENT = AGENT
t28.WINDOW = WINDOW
t30.WINDOW = WINDOW


# ---------------------------------------------------------------- older tests on the new files

class Old0008(t8.LiveMessages):
    pass


class Old0019(t19.AdminOnly):
    pass


class Old0020(t20.OpenLinks):
    pass


class Old0021Routing(t21.Routing):
    pass


class Old0023Targeted(t23.Targeted):
    pass


class Old0024Polls(t24.PollMessages):
    pass


class Old0025Laptop(t25.CorrectOnLaptop):
    pass


class Old0025Teacher(t25.CorrectOnTeacher):
    pass


class Old0028Agent(t28.Agent):
    pass


class Old0028Window(t28.Window):
    pass


class Old0030Choices(t30.Choices):
    pass


# ---------------------------------------------------------------- lab-sound

class LabSound(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "calls.log")
        open(self.log, "w").close()
        os.makedirs(os.path.join(self.dir, "bin"))
        os.makedirs(os.path.join(self.dir, "system"))
        open(os.path.join(self.dir, "system", "bell.oga"), "w").close()
        for name in ("player", "wpctl"):
            t28.fake_command(os.path.join(self.dir, "bin", name), self.log)
        self.env = dict(os.environ, PATH=os.path.join(self.dir, "bin") + ":" + os.environ["PATH"],
                        LAB_SOUND_DIR=SOUNDS, LAB_SOUND_SYSTEM_DIR=os.path.join(self.dir, "system"),
                        LAB_SOUND_PLAYER=os.path.join(self.dir, "bin", "player"))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_sound(self, *args):
        result = subprocess.run(["bash", LAB_SOUND, *args], env=self.env, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
        with open(self.log) as handle:
            return result, handle.read().splitlines()

    def test_list_names_every_sound(self):
        result, _ = self.run_sound("--list")
        self.assertEqual(result.stdout.split(), ["applause", "bell", "tada", "tick"])   # no ding file here

    def test_plays_a_lab_sound_and_a_system_sound(self):
        result, calls = self.run_sound("tada")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [f"player {os.path.join(SOUNDS, 'tada.wav')}"])
        self.run_sound("bell")
        with open(self.log) as handle:
            self.assertIn(f"player {os.path.join(self.dir, 'system', 'bell.oga')}", handle.read())

    def test_volume_first_then_the_sound(self):
        _, calls = self.run_sound("--volume", "60", "tick")
        self.assertEqual(calls, ["wpctl set-mute @DEFAULT_AUDIO_SINK@ 0", "wpctl set-volume @DEFAULT_AUDIO_SINK@ 60%",
                                 f"player {os.path.join(SOUNDS, 'tick.wav')}"])

    def test_bad_volume_is_ignored(self):
        _, calls = self.run_sound("--volume", "250", "tick")
        self.assertEqual(calls, [f"player {os.path.join(SOUNDS, 'tick.wav')}"])

    def test_refuses_unknown_names_and_paths(self):
        for name in ("nope", "../tada", "/etc/passwd", "Tada", "", "ding"):
            result, calls = self.run_sound(name)
            self.assertEqual(result.returncode, 1, name)
            self.assertEqual(calls, [], name)

    def test_sound_files_are_short_mono_wavs(self):
        import wave
        for name in ("tick", "tada", "applause"):
            with wave.open(os.path.join(SOUNDS, name + ".wav")) as sound:
                self.assertEqual(sound.getnchannels(), 1)
                self.assertLess(sound.getnframes() / sound.getframerate(), 4)


# ---------------------------------------------------------------- listener: "sound" messages

class SoundMessages(t20.OpenLinks):
    def send(self, **fields):
        message = {"id": "s" + str(len(self.commands)) + str(time.time()), "title": "T", "text": "", "code": ""}
        message.update(fields)
        listener.show(message, admins_only=fields.pop("admins_only", False))

    def programs(self):
        return [(user, os.path.basename(program)) for user, program, _last in self.commands]

    def test_sound_only_plays_for_everyone_without_a_popup(self):
        self.send(sound="applause")
        self.assertEqual(self.programs(), [(u, "lab-sound") for u in ("administrator", "studenttest1", "tdsb-123456789")])
        self.assertEqual({last for _u, _p, last in self.commands}, {"applause"})
        self.assertEqual(self.windows, [])

    def test_sound_with_text_also_pops_up(self):
        self.send(sound="ding", text="Well done!")
        self.assertEqual(self.programs().count(("studenttest1", "lab-sound")), 1)
        self.assertEqual(len(self.windows), 3)

    def test_volume_goes_to_lab_sound_not_lab_present(self):
        self.send(sound="tada", volume=60)
        self.assertNotIn("lab-present", [p for _u, p in self.programs()])
        self.assertEqual(len(self.commands), 3)

    def test_admins_only_sound(self):
        self.send(sound="bell", admins_only=True)
        self.assertEqual(self.programs(), [("administrator", "lab-sound")])

    def test_bad_sound_names_play_nothing(self):
        for bad in ("../../bin/sh", "Applause", 5, "x" * 40):
            self.commands.clear()
            self.windows.clear()
            self.send(sound=bad)
            self.assertNotIn("lab-sound", [p for _u, p in self.programs()], bad)
            self.assertEqual(len(self.windows), 3, bad)      # old behaviour: a pop-up with the title

    def test_safe_sound(self):
        self.assertEqual(listener.safe_sound("tada"), "tada")
        self.assertIsNone(listener.safe_sound("tada;rm"))
        self.assertIsNone(listener.safe_sound(None))


# ---------------------------------------------------------------- agent: the end countdown

class EndCountdown(t28.Agent):
    def started(self):
        message = {"id": "m1", "sent": time.time(), "quiz_start": {"sitting": "made-up-1", "title": "Made-up Quiz"}}
        self.agent.handle_start(message)
        self.path = os.path.join(self.agent.sitting_dir("made-up-1"), "start.json")

    def end(self, countdown=None, sent=None, keep=()):
        body = {"sitting": "made-up-1", "except": list(keep)}
        if countdown is not None:
            body["countdown"] = countdown
        self.agent.handle_end({"id": "e" + str(time.time()), "sent": sent or time.time(), "quiz_end": body})
        return self.agent.read_json(self.path)

    def test_countdown_sets_the_end_time_then_ends(self):
        self.started()
        now = time.time()
        record = self.end(countdown=10, sent=now)
        self.assertFalse(record["ended"])
        self.assertAlmostEqual(record["end_at"], now + 10, places=3)
        self.agent.finish_countdowns(now + 5)
        self.assertFalse(self.agent.read_json(self.path)["ended"])
        self.agent.finish_countdowns(now + 10)
        self.assertTrue(self.agent.read_json(self.path)["ended"])

    def test_a_late_message_ends_right_away(self):
        self.started()
        self.end(countdown=10, sent=time.time() - 60)
        self.agent.finish_countdowns()
        self.assertTrue(self.agent.read_json(self.path)["ended"])

    def test_end_without_countdown_cuts_the_countdown_short(self):
        self.started()
        self.end(countdown=60)
        record = self.end()
        self.assertTrue(record["ended"])
        self.assertNotIn("end_at", record)

    def test_countdown_never_reopens_an_ended_quiz(self):
        self.started()
        self.end()
        record = self.end(countdown=30)
        self.assertTrue(record["ended"])
        self.assertNotIn("end_at", record)

    def test_second_countdown_keeps_the_first_end_time(self):
        self.started()
        first = self.end(countdown=10)["end_at"]
        self.assertEqual(self.end(countdown=99)["end_at"], first)

    def test_bad_countdowns_end_right_away(self):
        for bad in (0, -5, 601, True, "10", 2.5):
            self.started()
            record = self.agent.read_json(self.path)
            record.update(ended=False)
            record.pop("end_at", None)
            self.agent.write_json(self.path, record)
            self.assertTrue(self.end(countdown=bad)["ended"], bad)


# ---------------------------------------------------------------- window: sounds and the countdown bar

SOUND_VERSION = dict(t30.CHOICE_VERSION, sounds=True)


class WindowSounds(t28.Window):
    def write_version(self, version):
        with open(os.path.join(self.run_dir, self.sitting, f"{self.user}.json"), "w") as handle:
            json.dump({"sitting": self.sitting, "title": "Made-up Quiz", "total": 5, "account": self.user, **version},
                      handle)

    def sound_window(self, script, status=None, before=None):
        sounds_log = os.path.join(self.dir, "sounds.log")
        fake = os.path.join(self.dir, "fake-lab-sound")
        t28.fake_command(fake, sounds_log)
        old = os.environ.get("LAB_QUIZ_SOUND")
        os.environ["LAB_QUIZ_SOUND"] = fake
        os.environ["LAB_QUIZ_SOUND_DIR"] = SOUNDS
        try:
            if before:
                before()
            return self.window(script, status=status)
        finally:
            if old is None:
                os.environ.pop("LAB_QUIZ_SOUND", None)
            else:
                os.environ["LAB_QUIZ_SOUND"] = old

    def test_hand_in_ticks_then_cheers(self):
        self.write_version(SOUND_VERSION)
        shown = self.sound_window({"first": "Team", "last": "Rocket", "handin": "HAND IN"}, status="handed")
        self.assertEqual(shown["state"], "handed")
        self.assertEqual(shown["played"][-1], "tada")                  # no yay.wav yet
        self.assertGreaterEqual(shown["played"].count("tick"), 1)

    def test_quiz_without_sounds_stays_silent(self):
        shown = self.sound_window({"first": "Sam", "last": "Lee", "handin": "HAND IN"}, status="handed")
        self.assertEqual(shown["played"], [])

    def test_countdown_bar_and_ticks(self):
        self.write_version(SOUND_VERSION)
        status_path = os.path.join(self.run_dir, self.sitting, f"{self.user}.status")

        def countdown():
            with open(status_path, "w") as handle:
                json.dump({"state": "open", "ends_at": time.time() + 4}, handle)

            def finish():
                time.sleep(5)
                with open(status_path, "w") as handle:
                    json.dump({"state": "ended"}, handle)
            import threading
            threading.Thread(target=finish, daemon=True).start()
        shown = self.sound_window({"first": "Team", "last": "Rocket", "wait_end": True}, before=countdown)
        self.assertEqual(shown["state"], "ended")
        self.assertIn("Your teacher is ending the quiz", shown["ending"])
        self.assertGreaterEqual(shown["played"].count("tick"), 2)
        self.assertEqual(shown["played"][-1], "tada")


# ---------------------------------------------------------------- install script

class InstallScript(unittest.TestCase):
    def test_installs_every_file_it_ships(self):
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read()
        self.assertTrue(script.startswith("#!/bin/bash\n"))
        self.assertIn('source "$LAB_UPDATER_HELPERS"', script)
        for path in ("usr/local/bin/lab-sound", "usr/local/lib/lab-messages/lab-messages-listener.py",
                     "usr/local/lib/lab-quiz/lab-quiz-agent.py", "usr/local/lib/lab-quiz/quiz-window.py"):
            self.assertIn(f"files/{path}", script)
        self.assertIn("files/usr/local/share/lab-sounds/*.wav", script)
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(UPDATE, "install.sh")]).returncode, 0)
        self.assertEqual(subprocess.run(["bash", "-n", LAB_SOUND]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
