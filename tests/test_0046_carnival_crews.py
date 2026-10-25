#!/usr/bin/env python3
"""Run every 0043/0044 behavior on 0046, then a real Carnival via ntfy and GTK."""
import os
import sys
import json
import random
import unittest
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Keep all throwaway keys, servers and displays in this scratch project.
os.environ['TMPDIR'] = str(HERE.parent.parent / '.test-tmp')
Path(os.environ['TMPDIR']).mkdir(exist_ok=True)
# Broadway uses Unix sockets: keep paths below sockaddr_un's limit.
tempfile.tempdir = os.path.relpath(os.environ['TMPDIR'])
sys.path.insert(0, str(HERE))
import test_0044_crew_games as t44

t43 = t44.t43
UPDATE = HERE.parent / 'updates' / '0046-carnival-crews'
AGENT = str(UPDATE / 'files/usr/local/lib/lab-game/lab-game-agent.py')
WINDOW = str(UPDATE / 'files/usr/local/lib/lab-game/game-window.py')
agent = t43.load('lab_game_agent46', AGENT)
t44.agent = t43.agent = agent
t44.AGENT = t43.AGENT = AGENT
t44.WINDOW = t43.WINDOW = WINDOW

class ShortRuntime:
    @classmethod
    def setUpClass(cls):
        from unittest.mock import patch
        original = tempfile.mkdtemp
        def relative(*args, **kwargs):
            return os.path.relpath(original(*args, **kwargs))
        with patch.object(tempfile, 'mkdtemp', relative):
            super().setUpClass()

class Old0043Config(t44.Old0043Config):
    pass

class Old0043Signatures(t44.Old0043Signatures):
    pass

class Old0043GameState(t44.Old0043GameState):
    pass

class Old0043Deals(t44.Old0043Deals):
    pass

class Old0043Sessions(t44.Old0043Sessions):
    pass

class Old0043WholeGame(ShortRuntime, t44.Old0043WholeGame):
    pass

class Old0044State(t44.CrewState):
    pass

class Old0044WholeGame(ShortRuntime, t44.WholeCrewGame):
    pass

class Install(t44.Install):
    def test_install_script_installs_everything_it_ships(self):
        script = (UPDATE / 'install.sh').read_text()
        self.assertTrue(script.startswith('#!/bin/bash\n# 0046-carnival-crews'))
        self.assertIn('Needs 0043. Safe to re-run.', script)
        for path in (UPDATE / 'files').rglob('*.py'):
            self.assertIn('files/' + str(path.relative_to(UPDATE / 'files')) + ' ', script)
        self.assertIn('systemctl restart lab-game.service', script)

class LobbySessions(t43.Sessions):
    def test_empty_lobby_deal_stops_join_and_window_stays_closed(self):
        now = t43.time.time()
        self.state.apply(dict(t43.start_event(started=now), lobby=True, open_ended=True, crews=[]), now)
        sessions, outbox = agent.Sessions(self.state), []
        sessions.tick(outbox, now)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(len(outbox), 1)
        agent.write_deal(dict(game='g1', seq=2, account=t43.ME, cards=[], lobby=True))
        sessions.tick(outbox, now + 2 * agent.JOIN_RETRY_SECONDS)
        self.assertEqual(len(outbox), 1)
        self.assertEqual(len(self.opened), 1)  # closing a window never asks the agent to relaunch it

class CarnivalState(t44.CrewState):
    def test_lobby_go_done_and_replay(self):
        state = agent.State()
        event = dict(t44.crew_start(started=self.now), crews=[], lobby=True, open_ended=True)
        state.apply(event, self.now)
        state.apply(self.event(2, 'lobby', count=42), self.now)
        self.assertEqual(state.data['lobby_count'], 42)
        crews = [{'id': f'c{i}', 'name': f'Crew {i}', 'color': '#123456'} for i in range(12)]
        go = self.event(3, 'go', crews=crews, started=int(self.now)+10, deadline=int(self.now)+900)
        state.apply(go, self.now)
        state.apply(self.event(4, 'done', crew='c0', place=1, at=int(self.now)), self.now)
        self.assertEqual(len(state.data['crew_locks']), 12)
        self.assertIsNone(state.data['result'])
        state.apply(event, self.now)
        self.assertFalse(state.data['lobby'])
        self.assertEqual(state.data['done']['c0']['place'], 1)

    def test_private_explanation_and_action_size(self):
        saved = agent.RUN_DIR
        agent.RUN_DIR = t43.tempfile.mkdtemp(dir=t43.WORK)
        try:
            agent.prepare_dirs()
            payload = dict(game='c1', seq=2, account=t43.ME, cards=[], lobby=True)
            self.assertTrue(agent.write_deal(payload))
            event = dict(payload, type='explained', seq=3, lock='vault', text='First line\nSecond line', at=10)
            self.assertTrue(agent.write_explanation(event))
            self.assertFalse(agent.write_explanation(dict(event, seq=2, text='old')))
            path = Path(agent.RUN_DIR) / f'deal-{os.getuid()}.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['explanations']['vault']['text'], event['text'])
            agent.handle_body(self.state, t43.signed(event))
            self.assertNotIn('Second line', json.dumps(self.state.data))
            self.assertTrue(agent.write_explanation(dict(event, seq=4, text='Revised work')))
            agent.write_deal(dict(payload, seq=5, lobby=False))
            self.assertEqual(json.loads(path.read_text())['explanations']['vault']['text'], 'Revised work')
            host = t43.lab_game.Host(t43.lab_game.gamelib.Game.new('c1', t43.lab_game.gamelib.load_room('ghost-in-the-machine')))
            private = dict(event, seq=6, text='Only this student sees this work', laptops=['lab-a'])
            body = host.body(private).decode()
            self.assertNotIn(private['text'], body)
            saved_hostname = agent.HOSTNAME
            agent.HOSTNAME = 'lab-z'
            try:
                agent.handle_body(self.state, body)
            finally:
                agent.HOSTNAME = saved_hostname
            self.assertEqual(json.loads(path.read_text())['explanations']['vault']['text'], 'Revised work')
            agent.handle_body(self.state, body)
            self.assertEqual(json.loads(path.read_text())['explanations']['vault']['text'], private['text'])
            self.assertNotIn(private['text'], json.dumps(self.state.data))
            # File ownership, UTF-8 truncation and the encrypted wire limit all apply to explanations.
            action_path = Path(agent.action_dir()) / 'explain.json'
            action_path.write_text(json.dumps(dict(game='c1', type='explain', lock='vault', text='😀' * 400,
                                                  user='forged'), ensure_ascii=False))
            outbox = []
            agent.collect_actions(self.state, outbox)
            self.assertEqual(outbox[0]['user'], t43.ME)
            self.assertEqual(len(outbox[0]['text'].encode('utf-8')), 1200)
            self.assertLessEqual(len(agent.action_body(outbox[0])), 4096)
            action = agent.make_action(self.state, t43.ME, 'explain', lock='vault', text='é\n' * 400)
            self.assertLessEqual(len(agent.action_body(action)), 4096)
        finally:
            agent.RUN_DIR = saved

class WholeCarnival(ShortRuntime, t43.WholeGame):
    def test_a_whole_game(self):
        gl = t43.lab_game.gamelib
        game = gl.LobbyCrewGame.new('carnival-' + os.urandom(3).hex(), 'rigged-carnival', rng=random.Random(46))
        host = t43.lab_game.Host(game, rng=random.Random(46))
        host.queue([host.start_event()])
        key = t43.lab_game.private_key()
        path = Path(t43.RUN_DIR) / f'deal-{os.getuid()}.json'
        self.assertTrue(self.until(lambda: path.exists() and t43.read_json(path).get('game') == game.data['game'], host, key))
        for projector in ('0', '1'):
            out, err = self.run_window('', 300, host, key, projector)
            self.assertIn('1 students have joined', out, err)
            self.assertIn('LOBBY:', out)
        # Enough anonymous test participants for several crews.
        for i in range(16):
            host.queue(game.join(f'test{i}', 'lab-a', t43.time.time()))
        host.queue(game.go(t43.time.time(), random.Random(46)))
        self.assertTrue(self.until(lambda: bool(self.state.data['crews']), host, key))
        crew = game.crew_of(t43.ME)
        locks = game.rooms[crew]['locks']
        out, err = self.run_window('', 300, host, key)
        self.assertIn('CREW:YOU', out, err)
        self.assertIn('LOCK:', out)
        self.assertIn('EXPLAIN:', out)
        first = locks[0]
        out, err = self.run_window(f"guess:{first['id']}:{first['answers'][0]}", 2500, host, key)
        self.assertTrue(self.until(lambda: first['id'] in game.data['opened'][crew], host, key), err)
        out, err = self.run_window(f"explain:{first['id']}:We counted the arrangements.\nThen divided repeats.", 2500, host, key)
        self.assertIn('Saved ✓', out, err)
        self.assertIn('SENDING:Sending…', out)
        self.assertIn('Then divided repeats.', t43.read_json(path)['explanations'][first['id']]['text'])
        out, err = self.run_window('', 300, host, key)
        self.assertIn('Saved ✓', out, err)
        # Every remaining answer still traverses the real window, agent and host.
        for lock in locks[1:]:
            game.data['players'][t43.ME]['last_guess'] = 0
            out, err = self.run_window(f"guess:{lock['id']}:{lock['answers'][0]}", 1800, host, key)
            self.assertTrue(self.until(lambda: lock['id'] in game.data['opened'][crew], host, key), (lock['id'], out, err))
        self.assertIsNone(game.data['result'])
        out, err = self.run_window('leave', 300, host, key)
        self.assertIn('Case solved! Your crew placed #1', out, err)
        self.assertIn('LEAVE:True', out)
        self.assertIn("LEAVEPROMPT:You haven't written how your crew solved:", out)
        self.assertIn('Leave anyway?', out)
        self.assertIn('MISSING:', out)
        out, err = self.run_window('', 300, host, key, '1')
        self.assertIn('⭐', out, err)
        self.assertIn('Case solved! #1', out)
        self.assertNotIn('EXPLAIN:', out)
        host.queue(game.finish('ended', t43.time.time()))
        self.assertTrue(self.until(lambda: self.state.data['result'] == 'ended', host, key))
        out, err = self.run_window('', 300, host, key)
        self.assertIn('Your teacher ended the game.', out, err)
        self.assertNotIn(':input', out)
        self.assertIn(f"READONLY:{first['id']}:True", out)

def tearDownModule():
    t44.tearDownModule()

if __name__ == '__main__':
    unittest.main()
