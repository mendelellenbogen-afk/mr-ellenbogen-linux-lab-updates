#!/usr/bin/env python3
"""Tests for update 0044-crew-games: class games in crews (Cipher Heist).

Every 0043 test (agent, window, a whole escape room end to end) reruns on
0044's agent and window, so rooms without crews must work as before. Then
the crew parts: the agent keeps each crew's locks apart, reads a crew's
posts only when they are encrypted to its laptop, and records freezes and
the winner; and a whole crew game runs from the teacher's tools/lab-game
through a local ntfy to the real window (needs ntfy and gtk4-broadwayd).

    python3 -I update-repo/tests/test_0044_crew_games.py < /dev/null
"""

import json
import os
import random
import shutil
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_0043_class_games as t43   # noqa: E402

UPDATE = os.path.join(HERE, "..", "updates", "0044-crew-games")
FILES = os.path.join(UPDATE, "files")
AGENT = os.path.join(FILES, "usr", "local", "lib", "lab-game", "lab-game-agent.py")
WINDOW = os.path.join(FILES, "usr", "local", "lib", "lab-game", "game-window.py")

# The 0043 tests below now run on 0044's files.
agent = t43.load("lab_game_agent44", AGENT)
t43.agent, t43.AGENT, t43.WINDOW = agent, AGENT, WINDOW
ME = t43.ME


class Old0043Config(t43.Config):
    pass


class Old0043Signatures(t43.Signatures):
    pass


class Old0043GameState(t43.GameState):
    pass


class Old0043Deals(t43.DealsAndActions):
    pass


class Old0043Sessions(t43.Sessions):
    pass


class Old0043WholeGame(t43.WholeGame):
    pass


def crew_start(game="c1", seq=1, started=None):
    event = t43.start_event(game, seq, started)
    event["crews"] = [{"id": "red", "name": "Red Crew", "color": "#d1343e"},
                      {"id": "blue", "name": "Blue Crew", "color": "#2f6fe0"}]
    return event


class CrewState(unittest.TestCase):
    def setUp(self):
        self.state = agent.State()
        self.now = time.time()
        self.state.apply(crew_start(started=self.now), self.now)

    def event(self, seq, kind, **fields):
        return dict({"v": 1, "game": "c1", "seq": seq, "sent": int(self.now), "type": kind}, **fields)

    def test_each_crew_has_its_own_locks(self):
        apply = lambda e: self.state.apply(e, self.now)
        apply(self.event(2, "open", crew="red", lock="vault", who="Red Otter", color="#d1343e", reveal="R inside"))
        d = self.state.data
        self.assertEqual([c["id"] for c in d["crews"]], ["red", "blue"])
        self.assertTrue(d["crew_locks"]["red"]["vault"]["open"])
        self.assertEqual(d["crew_locks"]["blue"], {})
        self.assertFalse(self.state.lock_named("vault")["open"])                  # the shared list stays closed
        self.assertEqual(d["feed"][-1]["crew"], "red")
        apply(self.event(3, "open", crew="nobody", lock="exit", who="X"))          # not a crew of this game
        self.assertFalse(self.state.lock_named("exit")["open"])
        # A restart of the start event keeps what is open.
        self.state.apply(crew_start(seq=1, started=self.now), self.now)
        self.assertTrue(self.state.data["crew_locks"]["red"]["vault"]["open"])

    def test_freeze_hint_and_winner(self):
        apply = lambda e: self.state.apply(e, self.now)
        apply(self.event(2, "guess", crew="blue", lock="vault", who="Blue Koala", text="1111", cost=10,
                         frozen_until=int(self.now) + 10))
        self.assertEqual(self.state.data["frozen"], {"blue": int(self.now) + 10})
        self.assertIn("(frozen 10 s)", self.state.data["feed"][-1]["text"])
        self.assertEqual(self.state.data["deadline"], int(self.now) + 1800)       # the shared clock is untouched
        apply(self.event(3, "hint", crew="red", text="Look left"))
        self.assertEqual(self.state.data["hints"][-1]["crew"], "red")
        apply(self.event(4, "end", result="won", crew="blue", crew_name="Blue Crew", left=900))
        d = self.state.data
        self.assertEqual((d["result"], d["winner"], d["winner_name"], d["left"]), ("won", "blue", "Blue Crew", 900))
        plain = agent.State()
        plain.apply(t43.start_event("p1", started=self.now), self.now)
        plain.apply(dict(self.event(2, "end", result="won", crew="blue"), game="p1"), self.now)
        self.assertIsNone(plain.data["result"])                                   # no crews: not a result

    @unittest.skipUnless(t43.HAVE_TOOLS, "tools/lab-game is only on the teacher's computer")
    def test_crew_posts_reach_only_that_crews_laptops(self):
        host = t43.lab_game.Host(t43.lab_game.gamelib.Game.new("c1", t43.lab_game.gamelib.load_room("ghost-in-the-machine")))
        post = {"type": "post", "seq": 5, "crew": "red", "laptops": ["lab-a"],
                "post": {"n": 1, "who": "Red Otter", "color": "#d1343e", "text": "shift is 4", "at": 1}}
        body = host.body(post).decode()
        self.assertNotIn("shift is 4", body)
        agent.handle_body(self.state, body)
        self.assertEqual([(p["text"], p["crew"]) for p in self.state.data["posts"]], [("shift is 4", "red")])
        saved = agent.HOSTNAME
        agent.HOSTNAME = "lab-z"
        try:
            agent.handle_body(self.state, host.body(dict(post, seq=6, post=dict(post["post"], n=2))).decode())
        finally:
            agent.HOSTNAME = saved
        self.assertEqual(len(self.state.data["posts"]), 1)

    def test_deal_keeps_the_crew_and_marks_away_cards(self):
        saved = agent.RUN_DIR
        agent.RUN_DIR = t43.tempfile.mkdtemp(dir=t43.WORK)
        try:
            payload = {"game": "c1", "seq": 4, "account": ME, "codename": "Red Otter", "color": "#d1343e",
                       "crew": "red", "crew_name": "Red Crew", "crew_color": "#d1343e",
                       "cards": [{"title": "Mine", "text": "a"}, {"title": "For the Blue Crew: X", "text": "b",
                                                                  "away": True}]}
            self.assertTrue(agent.write_deal(payload))
            deal = t43.read_json(os.path.join(agent.RUN_DIR, f"deal-{os.getuid()}.json"))
            self.assertEqual((deal["crew"], deal["crew_name"]), ("red", "Red Crew"))
            self.assertEqual([c.get("away", False) for c in deal["cards"]], [False, True])
        finally:
            agent.RUN_DIR = saved


@unittest.skipUnless(t43.HAVE_TOOLS and shutil.which("ntfy") and shutil.which("gtk4-broadwayd"),
                     "needs tools/lab-game, ntfy and gtk4-broadwayd")
class WholeCrewGame(t43.WholeGame):
    """Teacher host -> local ntfy -> 0044 agent -> real window, a Cipher Heist in crews."""

    def test_a_whole_game(self):
        gamelib = t43.lab_game.gamelib
        crews = gamelib.crew_list(2)
        values = {c["id"]: gamelib.roll("cipher-heist", random.Random(5 + n), "medium") for n, c in enumerate(crews)}
        rooms = {c: gamelib.load_room("cipher-heist", v) for c, v in values.items()}
        game = gamelib.CrewGame.new("heist-test-" + os.urandom(3).hex(), rooms, crews, accounts=[ME], values=values)
        host = t43.lab_game.Host(game, rng=random.Random(5))
        host.queue([host.start_event()])
        key = t43.lab_game.private_key()
        deal_path = os.path.join(t43.RUN_DIR, f"deal-{os.getuid()}.json")
        self.assertTrue(self.until(lambda: (t43.read_json(deal_path).get("game") == game.data["game"]
                                            if os.path.exists(deal_path) else False), host, key),
                        "the cards never arrived")
        crew = game.crew_of(ME)
        room = rooms[crew]
        answer = {lock["id"]: lock["answers"][0] for lock in room["locks"]}
        crew_name = game.crews[crew]["name"]

        # Through the real window: the crew badge, a wrong guess (free at first), a post to the crew wall.
        out, err = self.run_window("guess:door:WRONGWORD|post:door shift please", 2500, host, key)
        self.assertIn(f"CREW:YOU'RE IN THE {crew_name.upper()}", out, err)
        self.assertIn("TITLE:Cipher Heist", out)
        self.assertIn("LOCK:vault:SEALED:no-input", out)
        self.assertTrue(self.until(lambda: len(self.state.data["posts"]) == 1, host, key))
        self.assertEqual(self.state.data["posts"][0]["crew"], crew)
        time.sleep(t43.agent.TICK_SECONDS + 4)
        out, err = self.run_window(f"guess:door:{answer['door']}", 3500, host, key)
        self.assertTrue(self.until(lambda: self.state.data["crew_locks"][crew].get("door", {}).get("open"),
                                   host, key))
        out, err = self.run_window("", 300, host, key)
        self.assertIn("LOCK:door:OPEN · ", out, err)
        self.assertIn("LOCK:alarm:LOCKED:input", out)
        self.assertIn(f"POST:{game.data['players'][ME]['codename']}:door shift please", out)
        self.assertIn("COST:Wrong guesses are free for now", out)

        # A late wrong guess freezes the crew: the window says so.
        game.data["players"][ME]["last_guess"] = 0
        game.data["started"] -= 400                                    # past the free minutes
        host.queue(game.guess(ME, "alarm", "WRONGAGAIN", time.time()))
        self.assertTrue(self.until(lambda: self.state.data["frozen"].get(crew, 0) > time.time(), host, key))
        out, err = self.run_window("", 300, host, key)
        self.assertRegex(out, r"COST:Your crew is frozen: \d+ s")

        # The projector shows the crews' progress, not their walls.
        out, err = self.run_window("", 300, host, key, projector="1")
        self.assertIn(f"SCORE:{crew}:✔ The Outer Door", out, err)
        self.assertNotIn("POST:", out)

        # The rest, then the vault: our crew wins and the game is over.
        game.data["frozen"] = {}
        for lock in ("alarm", "vault"):
            game.data["players"][ME]["last_guess"] = 0
            host.queue(game.guess(ME, lock, answer[lock].lower(), time.time()))
        self.assertTrue(self.until(lambda: self.state.data["result"] == "won", host, key))
        out, err = self.run_window("", 300, host, key)
        self.assertIn("BANNER:YOUR CREW CRACKED THE VAULT! You win the heist!", out, err)
        self.assertNotIn(":input", out)
        out, err = self.run_window("", 300, host, key, projector="1")
        self.assertIn(f"BANNER:{crew_name.upper()} CRACKED THE VAULT AND WINS THE HEIST!", out, err)


class Install(unittest.TestCase):
    def test_install_script_installs_everything_it_ships(self):
        script = t43.read(os.path.join(UPDATE, "install.sh"))
        for root, dirs, files in os.walk(FILES):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.relpath(os.path.join(root, name), FILES)
                self.assertIn(f"files/{path} ", script, path)
        self.assertIn("systemctl restart lab-game.service", script)
        self.assertTrue(script.startswith("#!/bin/bash\n# 0044-crew-games"))


def tearDownModule():
    shutil.rmtree(t43.WORK, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
