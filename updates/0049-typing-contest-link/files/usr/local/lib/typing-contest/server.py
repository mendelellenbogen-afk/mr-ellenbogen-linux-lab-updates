#!/usr/bin/env python3
"""Typing contest HTTP service and durable private results.

Works offline. Booth laptops linked with the same booth code (0049) also share their runs,
encrypted with a key made from the code, through the lab message server (ntfy.sh as the
fallback), so the Top 10 and Full results cover every linked laptop."""
import argparse
import base64
from datetime import datetime
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RUDE = ('fuck', 'shit', 'bitch', 'asshole', 'bastard', 'cunt', 'dick', 'pussy')
def nickname_ok(name):
    folded = name.lower().translate(str.maketrans('01345', 'oieas'))
    return not any(word in folded for word in RUDE)

def who(row):
    """The key that groups a student's runs: the booth-wide one when the run was made while
    linked, else this laptop's own."""
    return row.get('bplayer') or row['player']

CODE_LETTERS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
def normalize_code(code):
    code = re.sub(r'[\s-]', '', code or '').upper()
    if not re.fullmatch(f'[{CODE_LETTERS}]{{12}}', code): raise ValueError('A booth code has 12 letters and digits, like ABCD-EFGH-JKMN.')
    return f'{code[:4]}-{code[4:8]}-{code[8:]}'

def read_servers():
    """Lab server first, then ntfy.sh (as the laptops' other lab tools, 0038)."""
    if os.environ.get('TYPING_CONTEST_SERVERS'):
        return [s.rstrip('/') for s in os.environ['TYPING_CONTEST_SERVERS'].split(',') if s]
    found = {}
    try:
        for line in Path('/etc/lab-messages/config').read_text().splitlines():
            key, _, value = line.partition('=')
            if key.strip() in ('PRIMARY_SERVER', 'SERVER') and value.strip().startswith('https://'):
                found[key.strip()] = value.strip().rstrip('/')
    except OSError:
        pass
    servers = [found[k] for k in ('PRIMARY_SERVER', 'SERVER') if k in found]
    return servers or ['https://lab-messages.tail72844f.ts.net', 'https://ntfy.sh']

def valid_remote(row):
    """A run from another linked laptop, checked so a bad one can't break this laptop."""
    try:
        ok = (row.get('v') == 1 and re.fullmatch(r'[0-9a-f]{16}', row['run_id']) and re.fullmatch(r'[0-9a-f]{64}', row['bplayer'])
              and re.fullmatch(r'[0-9a-f]{64}', row['player']) and re.fullmatch(r'[0-9a-f]{12}', row['laptop'])
              and re.fullmatch(r"[A-Za-z0-9 _\-.!']{1,16}", row['nickname']) and nickname_ok(row['nickname'])
              and isinstance(row['id_hint'], str) and len(row['id_hint']) <= 12 and isinstance(row['time'], str) and len(row['time']) <= 40
              and isinstance(row['sentence_id'], str) and len(row['sentence_id']) <= 40 and type(row['finished']) is bool
              and all(type(row[k]) in (int, float) and 0 <= row[k] <= limit for k, limit in (('wpm', 220), ('accuracy', 100)))
              and (row['enc_id'] is None or isinstance(row['enc_id'], dict))
              and type(row.get('small_prize', False)) is bool)
    except (KeyError, TypeError):
        return False
    if ok: row['qualifies'] = row['finished'] and row['accuracy'] >= 90
    return bool(ok)

class Store:
    def __init__(self, data, share, teacher_key):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data.chmod(0o700)
        self.share = Path(share)
        raw = (self.share / 'sentences.js').read_text()
        self.sentences = {s['id']: s['text'] for s in json.loads(raw.split('/* SENTENCES_START */')[1].split('/* SENTENCES_END */')[0])}
        salt = self.data / 'player-salt'
        try:
            fd = os.open(salt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as f:
                f.write(os.urandom(32)); f.flush(); os.fsync(f.fileno())
        salt.chmod(0o600)
        self.salt = salt.read_bytes()
        self.teacher = serialization.load_pem_public_key(Path(teacher_key).read_bytes()) if Path(teacher_key).exists() else None
        self.path = self.data / 'results.jsonl'
        self.rows = []
        if self.path.exists():
            self.path.chmod(0o600)
            for line in self.path.read_text().splitlines():
                try:
                    row = json.loads(line)
                    if row.get('v') == 1: self.rows.append(row)
                except (ValueError, AttributeError): pass
        self.hints = {}   # player -> ID hint of the latest run (0047 runs show 4 digits, later 5)
        self.remote = {}  # run_id -> run from another linked laptop (booth-runs.jsonl)
        self.lock = threading.RLock()
        self.booth = Booth(self)

    def all_rows(self):
        return sorted(self.rows + list(self.remote.values()), key=lambda r: r['time'])

    def owners(self):
        """player -> locked nickname, and folded nickname -> player (first use wins)."""
        locked, taken = {}, {}
        for row in self.all_rows():
            self.hints[who(row)] = row['id_hint']
            if who(row) not in locked and row['nickname'].casefold() not in taken:
                locked[who(row)] = row['nickname']; taken[row['nickname'].casefold()] = who(row)
        return locked, taken

    def identify(self, obj):
        """Check the ID and nickname; returns (id, player, bplayer, nickname, returning). A
        returning ID keeps its first nickname (on this laptop, or on all linked laptops); a
        nickname can't be taken by another ID."""
        if not isinstance(obj, dict): raise ValueError('Expected a JSON object.')
        sid = obj.get('student_id')
        if not isinstance(sid,str) or not re.fullmatch(r'[A-Za-z0-9]{3,27}', sid.replace(' ','')): raise ValueError('Enter an ID with 3 to 27 letters or digits.')
        sid = sid.replace(' ','')
        player = hmac.new(self.salt,sid.upper().encode(),hashlib.sha256).hexdigest()
        bplayer = self.booth.player(sid)
        key = bplayer or player
        name = obj.get('nickname')
        name = name.strip() if isinstance(name,str) else ''
        with self.lock:
            locked, taken = self.owners()
        if key in locked:
            return sid, player, bplayer, locked[key], True
        if not name: raise ValueError('Enter a nickname.')
        if not nickname_ok(name): raise ValueError('Please choose another nickname.')
        if not re.fullmatch(r"[A-Za-z0-9 _\-.!']{1,16}",name): raise ValueError('Use 1 to 16 letters, digits, spaces or _-.!\' in your nickname.')
        if taken.get(name.casefold(), key) != key: raise ValueError('That nickname is taken. Please choose another.')
        return sid, player, bplayer, name, False

    def check(self, obj):
        sid, player, bplayer, name, returning = self.identify(obj)
        return dict(ok=True, nickname=name, returning=returning)

    def prize_check(self, group, wpm, accuracy, qualifies, once=True):
        """Small prize (teacher, 2026-10-27): a run with 90 %+ accuracy that places in the top 10 %
        of everyone who has played so far (this student included), once per student."""
        rows = self.all_rows()
        if not qualifies or (once and any(who(r) == group and r.get('small_prize') for r in rows)): return False
        players = {who(r) for r in rows} | {group}
        bests = {}
        for r in rows:
            if r['qualifies'] and who(r) != group: bests[who(r)] = max(bests.get(who(r), 0), r['wpm'])
        ahead = sum(1 for w in bests.values() if w > wpm)
        return ahead + 1 <= max(1, -(-len(players) // 10))

    def best(self):
        result = {}
        for row in self.all_rows():
            if row['qualifies']:
                old = result.get(who(row))
                if old is None or (-row['wpm'], -row['accuracy'], row['time']) < (-old['wpm'], -old['accuracy'], old['time']):
                    result[who(row)] = row
        return sorted(result.values(), key=lambda r: (-r['wpm'], -r['accuracy'], r['time']))

    def top(self):
        locked = self.owners()[0]
        return [dict(rank=i, nickname=locked.get(who(r), r['nickname']), id_hint=self.hints[who(r)], **{k:r[k] for k in ('wpm','accuracy')}, when=r['time']) for i,r in enumerate(self.best()[:10],1)]

    def results(self):
        """Every player on this laptop: those with a qualifying run first (best of those), then
        the rest by their best run. For the booth's final results; no full IDs."""
        with self.lock:
            locked = self.owners()[0]
            best, runs = {}, {}
            rows = self.all_rows()
            prized = {who(r) for r in rows if r.get('small_prize')}
            for row in rows:
                runs[who(row)] = runs.get(who(row), 0) + 1
                order = (not row['qualifies'], -row['wpm'], -row['accuracy'], row['time'])
                if who(row) not in best or order < best[who(row)][0]:
                    best[who(row)] = (order, row)
            ranked = sorted(best.values(), key=lambda item: item[0])
            return dict(players=[dict(rank=i, nickname=locked[who(r)], id_hint=self.hints[who(r)],
                                      wpm=r['wpm'], accuracy=r['accuracy'], qualified=r['qualifies'],
                                      runs=runs[who(r)], small_prize=who(r) in prized, when=r['time']) for i, (_, r) in enumerate(ranked, 1)],
                        runs=len(rows), linked=self.booth.linked, generated=datetime.now().astimezone().isoformat())

    def board(self):
        with self.lock:
            today = datetime.now().date().isoformat()
            rows = [r for r in self.all_rows() if r['time'].startswith(today)]
            return dict(top=self.top(), runs_today=len(rows), players_today=len({who(r) for r in rows}), booth=self.booth.status())

    def submit(self, obj):
        sid, player, bplayer, name, returning = self.identify(obj)
        group = bplayer or player
        sentence = obj.get('sentence_id')
        if not isinstance(sentence,str) or sentence not in self.sentences: raise ValueError('Unknown sentence.')
        for key in ('typed_chars','correct_keys','total_keys','elapsed_ms'):
            if type(obj.get(key)) is not int or obj[key] < 0: raise ValueError('Invalid run numbers.')
        typed, correct, total, elapsed = (obj[k] for k in ('typed_chars','correct_keys','total_keys','elapsed_ms'))
        finished = obj.get('finished')
        if type(finished) is not bool: raise ValueError('Invalid finish flag.')
        if elapsed < 3000 or elapsed > 300000 or total < typed or correct > total or correct < typed or typed > len(self.sentences[sentence]): raise ValueError('Impossible run.')
        if finished and typed != len(self.sentences[sentence]): raise ValueError('Incomplete sentence.')
        speed = typed * 12000 / elapsed
        if speed > 220: raise ValueError('Impossible run.')
        accuracy = correct * 100 / total if total else 0.0
        enc = None
        if self.teacher:
            secret = AESGCM.generate_key(bit_length=256); nonce = os.urandom(12)
            enc = dict(zip(('key','nonce','data'), (base64.b64encode(x).decode() for x in (self.teacher.encrypt(secret,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None)),nonce,AESGCM(secret).encrypt(nonce,sid.encode(),None)))))
        row = dict(v=1,time=datetime.now().astimezone().isoformat(),nickname=name,id_hint='•••'+sid[-5:],player=player,enc_id=enc,sentence_id=sentence,wpm=round(speed,1),accuracy=round(accuracy,1),finished=finished,qualifies=finished and accuracy >= 90,elapsed_ms=elapsed,typed_chars=typed,correct_keys=correct,total_keys=total,run_id=secrets.token_hex(8))
        if bplayer: row.update(bplayer=bplayer, laptop=self.booth.laptop)
        with self.lock:
            # Another ID may have claimed this nickname while the run was going.
            locked, taken = self.owners()
            if group not in locked and taken.get(name.casefold(), group) != group: raise ValueError('That nickname is taken. Please choose another.')
            row['nickname'] = locked.get(group, name)
            if self.prize_check(group, row['wpm'], row['accuracy'], row['qualifies']): row['small_prize'] = True
            # "Already won" only for a run that would have won (top 10 %) without the once rule.
            already = not row.get('small_prize') and any(who(r) == group and r.get('small_prize') for r in self.all_rows()) \
                and self.prize_check(group, row['wpm'], row['accuracy'], row['qualifies'], once=False)
            # Discard an incomplete final line left by an interrupted write.
            if self.path.exists():
                with self.path.open('rb+') as f:
                    content=f.read()
                    if content and not content.endswith(b'\n'):
                        f.truncate(content.rfind(b'\n')+1)
            fd = os.open(self.path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
            os.chmod(self.path,0o600)
            with os.fdopen(fd,'a') as f:
                f.write(json.dumps(row,ensure_ascii=True)+'\n'); f.flush(); os.fsync(f.fileno())
            self.rows.append(row)
            self.hints[group] = row['id_hint']
            best = self.best()
            rank = next((i for i,r in enumerate(best,1) if who(r)==group),None)
            result = dict(ok=True,nickname=row['nickname'],wpm=row['wpm'],accuracy=row['accuracy'],qualifies=row['qualifies'],rank=rank if rank and rank<=10 else None,personal_best=next((r['wpm'] for r in best if who(r)==group),None),top=self.top(),
                          small_prize=bool(row.get('small_prize')),prize_already=already)
        if bplayer: self.booth.wake.set()
        return result

class Booth:
    """Links booth laptops that share a booth code. Every run made while linked is sent,
    encrypted with a key made from the code, to an ntfy topic made from the code; every
    linked laptop reads the topic and adds the other laptops' runs (booth-runs.jsonl).
    Only laptops with the code can read the runs or add new ones."""

    def __init__(self, store):
        self.store = store
        self.config = store.data / 'booth.json'
        self.remote_path = store.data / 'booth-runs.jsonl'
        self.sent_path = store.data / 'booth-sent.json'
        self.servers = read_servers()
        self.hostname = os.environ.get('TYPING_CONTEST_HOSTNAME') or socket.gethostname()
        self.interval = float(os.environ.get('TYPING_CONTEST_SYNC_SECONDS', '10'))
        self.wake = threading.Event()
        self.code = None
        self.since = {}           # server -> id of the last message read
        self.last_ok = None
        self.error = ''
        self.cycle = 0
        try:
            self.set_code(json.loads(self.config.read_text())['code'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if self.code:
            self.sent = set(self.read_json(self.sent_path, []))
            for line in self.read_lines(self.remote_path):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and valid_remote(row): store.remote[row['run_id']] = row
        else:
            self.sent = set()

    @staticmethod
    def read_json(path, default):
        try: return json.loads(path.read_text())
        except (OSError, ValueError): return default

    @staticmethod
    def read_lines(path):
        try: return path.read_text().splitlines()
        except OSError: return []

    def set_code(self, code):
        self.code = normalize_code(code)
        root = hashlib.pbkdf2_hmac('sha256', self.code.encode(), b'typing-contest-booth-v1', 200000)
        part = lambda label: hmac.new(root, label, hashlib.sha256).digest()
        self.topic = 'mrellenbogen-lab-typing-' + part(b'topic').hex()[:24]
        self.aead = AESGCM(part(b'encrypt'))
        self.id_key = part(b'player')
        self.laptop = hmac.new(part(b'laptop'), self.hostname.encode(), hashlib.sha256).hexdigest()[:12]

    @property
    def linked(self):
        return self.code is not None

    def player(self, sid):
        return hmac.new(self.id_key, sid.upper().encode(), hashlib.sha256).hexdigest() if self.code else None

    def write_private(self, path, text):
        tmp = path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)

    def change(self, obj):
        """POST /api/booth: create a new code, join with a code, or leave."""
        action = obj.get('action') if isinstance(obj, dict) else None
        with self.store.lock:
            if action == 'create':
                code = ''.join(secrets.choice(CODE_LETTERS) for _ in range(12))
            elif action == 'join':
                code = obj.get('code') if isinstance(obj.get('code'), str) else ''
            elif action == 'leave':
                code = None
            else:
                raise ValueError('Unknown booth action.')
            if code is not None:
                code = normalize_code(code)
                if code == self.code: return self.status()
            # A new booth starts with no runs from other laptops.
            self.store.remote.clear(); self.sent = set(); self.since = {}; self.last_ok = None; self.error = ''
            for path in (self.remote_path, self.sent_path): path.unlink(missing_ok=True)
            if code is None:
                self.config.unlink(missing_ok=True); self.code = None
            else:
                self.set_code(code)
                self.write_private(self.config, json.dumps({'code': self.code}))
        self.wake.set()
        return self.status()

    def status(self):
        laptops = {r['laptop'] for r in self.store.remote.values()}
        if self.code: laptops.add(self.laptop)
        pending = sum(1 for r in self.store.rows if r.get('bplayer') and r['run_id'] not in self.sent) if self.code else 0
        return dict(linked=self.linked, code=self.code, laptops=len(laptops), pending=pending,
                    last_ok=self.last_ok, error=self.error)

    def request(self, url, data=None):
        req = urllib.request.Request(url, data=data, method='POST' if data is not None else 'GET',
                                     headers={'User-Agent': 'typing-contest/1'})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read()

    def publish(self):
        with self.store.lock:
            unsent = [r for r in self.store.rows if r.get('bplayer') and r['run_id'] not in self.sent]
            topic, aead = self.topic, self.aead
        for row in unsent:
            nonce = os.urandom(12)
            body = json.dumps({'tc': 1, 'n': base64.b64encode(nonce).decode(),
                               'd': base64.b64encode(aead.encrypt(nonce, json.dumps(row).encode(), topic.encode())).decode()})
            for server in self.servers:
                try:
                    self.request(f'{server}/{topic}', body.encode()); break
                except (OSError, ValueError):
                    continue
            else:
                raise OSError('could not send')
            with self.store.lock:
                if topic == self.topic:
                    self.sent.add(row['run_id'])
                    self.write_private(self.sent_path, json.dumps(sorted(self.sent)))

    def poll(self, server):
        with self.store.lock:
            topic, aead = self.topic, self.aead
        since = self.since.get(server, 'all')
        raw = self.request(f'{server}/{topic}/json?poll=1&since={urllib.parse.quote(since)}')
        new = []
        for line in raw.decode('utf-8', 'replace').splitlines():
            try:
                event = json.loads(line)
                if event.get('event') != 'message': continue
                since = event['id']
                outer = json.loads(event['message'])
                row = json.loads(aead.decrypt(base64.b64decode(outer['n']), base64.b64decode(outer['d']), topic.encode()))
            except Exception:
                continue    # not ours, or not readable with this booth's key
            if isinstance(row, dict) and valid_remote(row): new.append(row)
        with self.store.lock:
            if topic != self.topic: return
            self.since[server] = since
            mine = {r['run_id'] for r in self.store.rows}
            fresh = [r for r in new if r['run_id'] not in mine and r['run_id'] not in self.store.remote]
            for row in fresh: self.store.remote[row['run_id']] = row
            if fresh:
                with open(self.remote_path, 'a') as f:
                    os.chmod(self.remote_path, 0o600)
                    for row in fresh: f.write(json.dumps(row, ensure_ascii=True) + '\n')

    def sync(self):
        """One round: send this laptop's unsent runs, then read the lab server (and ntfy.sh
        every 6th round, to stay under its limits for the school's shared address)."""
        if not self.code: return
        self.cycle += 1
        errors = []
        try:
            self.publish()
        except OSError:
            errors.append('could not send runs (will retry)')
        servers = self.servers if self.cycle % 6 == 1 else self.servers[:1]
        read = 0
        for server in servers:
            try:
                self.poll(server); read += 1
            except (OSError, ValueError):
                pass
        if not read: errors.append('could not read the other laptops (will retry)')
        if read and not errors: self.last_ok = datetime.now().astimezone().isoformat()
        self.error = '; '.join(errors)

    def run(self):
        while True:
            self.wake.wait(self.interval); self.wake.clear()
            try:
                self.sync()
            except Exception as error:   # keep the contest running whatever happens
                self.error = f'sync problem: {error}'

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,value,mime='application/json'):
        body = json.dumps(value).encode() if mime=='application/json' else value
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers(); self.wfile.write(body)
    def allowed(self):
        hosts = (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        if self.headers.get('Host') not in hosts:
            self.reply(403,dict(ok=False,error='Invalid Host.')); return False
        if self.command=='POST' and self.headers.get('Origin') is not None and self.headers['Origin'] not in tuple('http://'+h for h in hosts):
            self.reply(403,dict(ok=False,error='Invalid Origin.')); return False
        return True
    def do_GET(self):
        if not self.allowed(): return
        path=urlsplit(self.path).path
        if path=='/api/board': self.reply(200,self.server.store.board()); return
        if path=='/api/results': self.reply(200,self.server.store.results()); return
        if path=='/api/booth': self.reply(200,self.server.store.booth.status()); return
        files={'/':'index.html','/index.html':'index.html','/style.css':'style.css','/app.js':'app.js','/sentences.js':'sentences.js'}
        if path not in files: self.reply(404,dict(ok=False,error='Not found.')); return
        name=files[path]; mime={'html':'text/html; charset=utf-8','css':'text/css; charset=utf-8','js':'text/javascript; charset=utf-8'}[name.split('.')[-1]]
        self.reply(200,(self.server.store.share/name).read_bytes(),mime)
    def do_POST(self):
        if not self.allowed(): return
        if self.path not in ('/api/result','/api/check','/api/booth'): self.reply(404,dict(ok=False,error='Not found.')); return
        try:
            length=int(self.headers.get('Content-Length','-1'))
            if not 0 <= length <= 16384 or self.headers.get_content_type()!='application/json' or self.headers.get('Transfer-Encoding'): raise ValueError('Send JSON of at most 16 KB.')
            self.connection.settimeout(5)
            body=json.loads(self.rfile.read(length))
            store=self.server.store
            result={'/api/check':store.check,'/api/booth':store.booth.change,'/api/result':store.submit}[self.path](body)
        except (ValueError, UnicodeError, TimeoutError) as e:
            self.reply(400,dict(ok=False,error=str(e))); return
        self.reply(200,result)

def create_server(data,share,teacher_key,port=0,sync=True):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.store=Store(data,share,teacher_key)
    server.daemon_threads=True
    if sync: threading.Thread(target=server.store.booth.run,daemon=True).start()
    return server

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--data',required=True); parser.add_argument('--share',required=True); parser.add_argument('--teacher-key',required=True)
    args=parser.parse_args()
    server=create_server(args.data,args.share,args.teacher_key)
    print(f'http://127.0.0.1:{server.server_port}/',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
if __name__=='__main__': main()
