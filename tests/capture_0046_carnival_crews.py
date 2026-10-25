"""Render the actual GTK window over Broadway and capture it with Chrome."""
import os, sys, json, time, subprocess, asyncio, base64, urllib.request
import websockets
from pathlib import Path
sys.path.insert(0, 'update-repo/tests')
os.environ['TMPDIR'] = '/proc/self/cwd/.test-tmp'
os.environ['XDG_CONFIG_HOME'] = '/proc/self/cwd/.test-tmp/config'
os.environ['XDG_CACHE_HOME'] = '/proc/self/cwd/.test-tmp/cache'
import tempfile
tempfile.tempdir = '.test-tmp'
import test_0046_carnival_crews as t
agent = t.agent
gl = t.t43.lab_game.gamelib
base = Path('.test-tmp/visual')
base.mkdir(parents=True, exist_ok=True)
Path('shots').mkdir(exist_ok=True)
agent.RUN_DIR = str(base)
game = gl.LobbyCrewGame.new('visual', 'rigged-carnival')
state = agent.State()
seq = 0
def apply(event):
    global seq
    seq += 1
    state.apply(dict(event, game='visual', seq=seq, sent=int(time.time())))
    if event['type'] == 'deal':
        agent.write_deal(dict(event, game='visual', seq=seq))
    state.write()
apply(game.start_event())
for event in game.join(t.t43.ME, 'lab-a', time.time()): apply(event)
os.environ['TMPDIR'] = '/proc/self/cwd/.test-tmp'
env = dict(os.environ, GDK_BACKEND='broadway', BROADWAY_DISPLAY=':97', XDG_RUNTIME_DIR=str(base), LAB_GAME_RUN_DIR=str(base), LAB_GAME_SOUND='')
for var in ('DISPLAY','WAYLAND_DISPLAY','LAB_GAME_SELFTEST'): env.pop(var, None)
daemon = subprocess.Popen(['gtk4-broadwayd', ':97'], env=env, stdout=subprocess.DEVNULL)
time.sleep(.5)
def shot(name, projector=False):
    chrome = subprocess.Popen(['/opt/google/chrome/chrome','--headless','--no-sandbox','--disable-gpu',
        '--disable-dev-shm-usage','--no-first-run','--no-default-browser-check','--password-store=basic',
        '--remote-debugging-port=9337', '--user-data-dir='+str((base/'chrome').resolve()),
        '--window-size=1366,768','about:blank'], env=env, stdout=subprocess.DEVNULL,
        stderr=open(base/'chrome.log','a'))
    async def capture():
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen('http://127.0.0.1:9337/json'))
                break
            except Exception:
                await asyncio.sleep(.1)
        async with websockets.connect(tabs[0]['webSocketDebuggerUrl'], max_size=20000000) as ws:
            counter = 0
            async def call(method, params={}):
                nonlocal counter
                counter += 1
                await ws.send(json.dumps(dict(id=counter, method=method, params=params)))
                while True:
                    data = json.loads(await ws.recv())
                    if data.get('id') == counter: return data.get('result', {})
            await call('Emulation.setDeviceMetricsOverride', dict(width=1366, height=768, deviceScaleFactor=1, mobile=False))
            await call('Page.navigate', dict(url='http://127.0.0.1:8177'))
            await asyncio.sleep(.5)
            e = dict(env, LAB_GAME_PROJECTOR=str(int(projector)), LAB_GAME_APP_ID='com.school.Capture' + name.replace('-', ''))
            window = subprocess.Popen(['python3','-I', t.WINDOW], env=e, stdout=subprocess.DEVNULL, stderr=open(base/'gtk.log','a'))
            try:
                await asyncio.sleep(2)
                result = await call('Page.captureScreenshot', dict(format='png'))
                Path('shots',name+'.png').write_bytes(base64.b64decode(result['data']))
            finally:
                window.terminate(); window.wait()
    try: asyncio.run(capture())
    finally: chrome.terminate(); chrome.wait()

try:
    shot('student-lobby'); shot('projector-lobby', True)
    for i in range(47): game.join('test'+str(i), 'lab-a', time.time())
    for event in game.go(time.time()): apply(event)
    crew = game.crew_of(t.t43.ME)
    for lock in game.rooms[crew]['locks']:
        if lock['kind'] == 'fraction': break
        game.data['players'][t.t43.ME]['last_guess'] = 0
        for event in game.guess(t.t43.ME, lock['id'], lock['answers'][0], time.time()): apply(event)
    # Keep a fraction lock and an opened justification together in the viewport.
    first = state.data['locks'][0]
    fraction = next(l for l in state.data['locks'] if l['kind']=='fraction')
    state.data['locks'] = [fraction, first] + [l for l in state.data['locks'] if l not in (first, fraction)]
    state.write()
    shot('student-playing')
    for lock in game.rooms[crew]['locks']:
        if lock['id'] in game.data['opened'][crew]: continue
        game.data['players'][t.t43.ME]['last_guess'] = 0
        for event in game.guess(t.t43.ME, lock['id'], lock['answers'][0], time.time()): apply(event)
    shot('student-done')
    for c in game.data['crews'][1:5]:
        lock = game.rooms[c['id']]['locks'][0]
        state.data['crew_locks'][c['id']][lock['id']] = {'open':True}
    state.write()
    shot('projector-scoreboard', True)
    for index, c in enumerate(game.data['crews']):
        state.data['crew_locks'][c['id']] = {l['id']: {'open':True} for l in state.data['locks']}
        state.data['done'][c['id']] = {'place':index+1, 'at':int(time.time())}
    state.write()
    shot('projector-all-finished', True)
finally:
    daemon.terminate(); daemon.wait()
    t.tearDownModule()
