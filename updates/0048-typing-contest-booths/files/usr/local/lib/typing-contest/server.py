#!/usr/bin/env python3
"""Offline typing contest HTTP service and durable private results."""
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
import threading
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RUDE = ('fuck', 'shit', 'bitch', 'asshole', 'bastard', 'cunt', 'dick', 'pussy')
def nickname_ok(name):
    folded = name.lower().translate(str.maketrans('01345', 'oieas'))
    return not any(word in folded for word in RUDE)

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
        self.lock = threading.RLock()

    def owners(self):
        """player -> locked nickname, and folded nickname -> player (first use wins)."""
        locked, taken = {}, {}
        for row in self.rows:
            self.hints[row['player']] = row['id_hint']
            if row['player'] not in locked and row['nickname'].casefold() not in taken:
                locked[row['player']] = row['nickname']; taken[row['nickname'].casefold()] = row['player']
        return locked, taken

    def identify(self, obj):
        """Check the ID and nickname; returns (id, player, nickname, returning). A returning
        ID keeps its first nickname on this laptop; a nickname can't be taken by another ID."""
        if not isinstance(obj, dict): raise ValueError('Expected a JSON object.')
        sid = obj.get('student_id')
        if not isinstance(sid,str) or not re.fullmatch(r'[A-Za-z0-9]{3,27}', sid.replace(' ','')): raise ValueError('Enter an ID with 3 to 27 letters or digits.')
        sid = sid.replace(' ','')
        player = hmac.new(self.salt,sid.upper().encode(),hashlib.sha256).hexdigest()
        name = obj.get('nickname')
        name = name.strip() if isinstance(name,str) else ''
        with self.lock:
            locked, taken = self.owners()
        if player in locked:
            return sid, player, locked[player], True
        if not name: raise ValueError('Enter a nickname.')
        if not nickname_ok(name): raise ValueError('Please choose another nickname.')
        if not re.fullmatch(r"[A-Za-z0-9 _\-.!']{1,16}",name): raise ValueError('Use 1 to 16 letters, digits, spaces or _-.!\' in your nickname.')
        if taken.get(name.casefold(), player) != player: raise ValueError('That nickname is taken on this laptop. Please choose another.')
        return sid, player, name, False

    def check(self, obj):
        sid, player, name, returning = self.identify(obj)
        return dict(ok=True, nickname=name, returning=returning)

    def best(self):
        result = {}
        for row in self.rows:
            if row['qualifies']:
                old = result.get(row['player'])
                if old is None or (-row['wpm'], -row['accuracy'], row['time']) < (-old['wpm'], -old['accuracy'], old['time']):
                    result[row['player']] = row
        return sorted(result.values(), key=lambda r: (-r['wpm'], -r['accuracy'], r['time']))

    def top(self):
        locked = self.owners()[0]
        return [dict(rank=i, nickname=locked.get(r['player'], r['nickname']), id_hint=self.hints[r['player']], **{k:r[k] for k in ('wpm','accuracy')}, when=r['time']) for i,r in enumerate(self.best()[:10],1)]

    def results(self):
        """Every player on this laptop: those with a qualifying run first (best of those), then
        the rest by their best run. For the booth's final results; no full IDs."""
        with self.lock:
            locked = self.owners()[0]
            best, runs = {}, {}
            for row in self.rows:
                runs[row['player']] = runs.get(row['player'], 0) + 1
                order = (not row['qualifies'], -row['wpm'], -row['accuracy'], row['time'])
                if row['player'] not in best or order < best[row['player']][0]:
                    best[row['player']] = (order, row)
            ranked = sorted(best.values(), key=lambda item: item[0])
            return dict(players=[dict(rank=i, nickname=locked[r['player']], id_hint=self.hints[r['player']],
                                      wpm=r['wpm'], accuracy=r['accuracy'], qualified=r['qualifies'],
                                      runs=runs[r['player']], when=r['time']) for i, (_, r) in enumerate(ranked, 1)],
                        runs=len(self.rows), generated=datetime.now().astimezone().isoformat())

    def board(self):
        with self.lock:
            today = datetime.now().date().isoformat()
            rows = [r for r in self.rows if r['time'].startswith(today)]
            return dict(top=self.top(), runs_today=len(rows), players_today=len({r['player'] for r in rows}))

    def submit(self, obj):
        sid, player, name, returning = self.identify(obj)
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
        row = dict(v=1,time=datetime.now().astimezone().isoformat(),nickname=name,id_hint='•••'+sid[-5:],player=player,enc_id=enc,sentence_id=sentence,wpm=round(speed,1),accuracy=round(accuracy,1),finished=finished,qualifies=finished and accuracy >= 90,elapsed_ms=elapsed,typed_chars=typed,correct_keys=correct,total_keys=total)
        with self.lock:
            # Another ID may have claimed this nickname while the run was going.
            locked, taken = self.owners()
            if player not in locked and taken.get(name.casefold(), player) != player: raise ValueError('That nickname is taken on this laptop. Please choose another.')
            row['nickname'] = locked.get(player, name)
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
            self.hints[player] = row['id_hint']
            best = self.best()
            rank = next((i for i,r in enumerate(best,1) if r['player']==player),None)
            return dict(ok=True,nickname=row['nickname'],wpm=row['wpm'],accuracy=row['accuracy'],qualifies=row['qualifies'],rank=rank if rank and rank<=10 else None,personal_best=next((r['wpm'] for r in best if r['player']==player),None),top=self.top())

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
        files={'/':'index.html','/index.html':'index.html','/style.css':'style.css','/app.js':'app.js','/sentences.js':'sentences.js'}
        if path not in files: self.reply(404,dict(ok=False,error='Not found.')); return
        name=files[path]; mime={'html':'text/html; charset=utf-8','css':'text/css; charset=utf-8','js':'text/javascript; charset=utf-8'}[name.split('.')[-1]]
        self.reply(200,(self.server.store.share/name).read_bytes(),mime)
    def do_POST(self):
        if not self.allowed(): return
        if self.path not in ('/api/result','/api/check'): self.reply(404,dict(ok=False,error='Not found.')); return
        try:
            length=int(self.headers.get('Content-Length','-1'))
            if not 0 <= length <= 16384 or self.headers.get_content_type()!='application/json' or self.headers.get('Transfer-Encoding'): raise ValueError('Send JSON of at most 16 KB.')
            self.connection.settimeout(5)
            body=json.loads(self.rfile.read(length))
            result=self.server.store.check(body) if self.path=='/api/check' else self.server.store.submit(body)
        except (ValueError, UnicodeError, TimeoutError) as e:
            self.reply(400,dict(ok=False,error=str(e))); return
        self.reply(200,result)

def create_server(data,share,teacher_key,port=0):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.store=Store(data,share,teacher_key)
    server.daemon_threads=True
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
