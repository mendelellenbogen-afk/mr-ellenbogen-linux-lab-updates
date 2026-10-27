#!/usr/bin/env python3
"""Tests for 0048-typing-contest-booths (server, store, page files, sentences). Loopback, temp data, synthetic IDs.

    python3 -I update-repo/tests/test_0047_typing_contest.py
"""
import base64
import concurrent.futures
import http.client
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
ROOT=Path(__file__).resolve().parents[1]/'updates'/'0048-typing-contest-booths'
SHARE=ROOT/'files/usr/local/share/typing-contest'
spec=importlib.util.spec_from_file_location('contest_server',ROOT/'files/usr/local/lib/typing-contest/server.py')
server=importlib.util.module_from_spec(spec); spec.loader.exec_module(server)

class ContestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.base=Path(self.temp.name); self.data=self.base/'data'
        self.key=self.base/'teacher.pem'; self.key.write_bytes(self.private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        self.start()
    def start(self):
        self.http=server.create_server(self.data,SHARE,self.key)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True); self.thread.start()
    def stop(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
    def tearDown(self): self.stop(); self.temp.cleanup()
    def request(self,path='/',obj=None,headers=None,method=None,raw=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
        hdr={'Host':f'127.0.0.1:{self.http.server_port}'}
        if obj is not None: raw=json.dumps(obj); hdr['Content-Type']='application/json'
        if headers: hdr.update(headers)
        conn.request(method or ('POST' if obj is not None or raw is not None else 'GET'),path,body=raw,headers=hdr)
        r=conn.getresponse(); body=r.read(); status=r.status; rh=dict(r.getheaders());conn.close()
        return status,body,rh
    def run_data(self,**kw):
        sentence=next(iter(self.http.store.sentences)); n=len(self.http.store.sentences[sentence])
        value=dict(student_id='SYNTHETIC987654',nickname='Rook',sentence_id=sentence,typed_chars=n,correct_keys=n,total_keys=n,elapsed_ms=30000,finished=True)
        value.update(kw);return value
    def submit(self,**kw):
        status,body,_=self.request('/api/result',self.run_data(**kw));return status,json.loads(body)
    def board(self):return json.loads(self.request('/api/board')[1])
    def test_page_files_and_headers(self):
        for path in ('/','/index.html','/style.css','/app.js','/sentences.js'):
            status,body,headers=self.request(path);self.assertEqual(status,200); self.assertTrue(body)
            self.assertEqual(headers['Cache-Control'],'no-store');self.assertIn("default-src 'self'",headers['Content-Security-Policy'])
        for path in ('/..','/../server.py','/%2e%2e/server.py','/results.jsonl','/player-salt','/missing','//etc/passwd'):
            self.assertEqual(self.request(path)[0],404,path)
    def test_host_origin_and_json_limits(self):
        self.assertEqual(self.request(headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/result',self.run_data(),headers={'Origin':'https://evil.example'})[0],403)
        for body,headers in [('{}',{'Content-Type':'text/plain'}),('x'*16385,{'Content-Type':'application/json'}),('{',{'Content-Type':'application/json'}),('[]',{'Content-Type':'application/json'})]:
            self.assertEqual(self.request('/api/result',raw=body,headers=headers)[0],400)
        self.assertEqual(self.request('/api/result',self.run_data(),headers={'Origin':f'http://localhost:{self.http.server_port}'})[0],200)
    def test_valid_run_and_privacy(self):
        status,r=self.submit();self.assertEqual(status,200);self.assertTrue(r['ok']);self.assertEqual(r['rank'],1)
        self.assertEqual(r['accuracy'],100);self.assertEqual(r['wpm'],round(self.run_data()['typed_chars']*.4,1))
        raw=(self.data/'results.jsonl').read_text();self.assertNotIn('SYNTHETIC987654',raw);self.assertNotIn('student_id',raw)
        row=json.loads(raw);enc=row['enc_id']; secret=self.private.decrypt(base64.b64decode(enc['key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        self.assertEqual(AESGCM(secret).decrypt(base64.b64decode(enc['nonce']),base64.b64decode(enc['data']),None),b'SYNTHETIC987654')
        self.assertEqual(row['id_hint'],'•••87654');self.assertEqual(len(row['player']),64)
        for name in ('results.jsonl','player-salt'):self.assertEqual((self.data/name).stat().st_mode&0o777,0o600)
        self.assertEqual(self.data.stat().st_mode&0o777,0o700)
        self.assertEqual(self.board()['runs_today'],1);self.assertEqual(self.board()['players_today'],1)
        self.assertNotIn('player',self.board()['top'][0]);self.assertNotIn('enc_id',json.dumps(r))
    def test_best_per_student_and_rebuild(self):
        self.submit(elapsed_ms=40000);self.submit(student_id='synthetic987654',elapsed_ms=30000);self.submit(elapsed_ms=50000)
        before=self.board();self.assertEqual(len(before['top']),1);self.assertEqual(before['players_today'],1);self.assertEqual(before['runs_today'],3)
        self.assertEqual(before['top'][0]['wpm'],round(self.run_data()['typed_chars']*.4,1))
        self.stop();self.start();self.assertEqual(self.board(),before)
    def test_low_accuracy_and_unfinished(self):
        n=self.run_data()['typed_chars']
        status,r=self.submit(total_keys=n*2);self.assertEqual(status,200);self.assertFalse(r['qualifies']);self.assertIsNone(r['rank'])
        status,r=self.submit(finished=False,typed_chars=10,correct_keys=10,total_keys=10)
        self.assertEqual(status,200);self.assertFalse(r['qualifies']);self.assertEqual(self.board()['top'],[])
    def test_empty_abandoned_run(self):
        status,r=self.submit(finished=False,typed_chars=0,correct_keys=0,total_keys=0,elapsed_ms=3000)
        self.assertEqual(status,200);self.assertEqual(r['accuracy'],0);self.assertFalse(r['qualifies'])
    def test_accuracy_and_time_break_speed_ties(self):
        n=self.run_data()['typed_chars']
        self.submit(student_id='FIRST123',nickname='First',total_keys=n+1)
        self.submit(student_id='SECOND123',nickname='Second')
        self.submit(student_id='THIRD123',nickname='Third')
        self.assertEqual([r['nickname'] for r in self.board()['top']],['Second','Third','First'])
    def test_impossible_runs(self):
        for kw in ({'elapsed_ms':2999},{'elapsed_ms':300001},{'elapsed_ms':3000},{'correct_keys':1000},{'total_keys':0},{'typed_chars':1},{'typed_chars':-1},{'elapsed_ms':True},{'finished':'yes'},{'sentence_id':'missing'},{'total_keys':2.5},{'correct_keys':0}):
            self.assertEqual(self.submit(**kw)[0],400,kw)
        self.assertEqual(self.board()['runs_today'],0)
    def test_id_and_nickname_validation(self):
        for sid in ('ab','a'*28,'abc-123','abc\n123','é123',123): self.assertEqual(self.submit(student_id=sid)[0],400)
        for name in ('','a'*17,'bad@name','Sh1tface','FUCK','b4st4rd'):
            self.assertEqual(self.submit(nickname=name)[0],400)
        self.assertEqual(self.submit(student_id=' ABC 123 ',nickname="  Knight-1!  ")[0],200)
    def test_missing_key(self):
        self.stop();self.key.unlink();self.start();self.assertEqual(self.submit()[0],200)
        self.assertIsNone(json.loads((self.data/'results.jsonl').read_text())['enc_id'])
    def test_top_ten_and_ties(self):
        for i in range(12):self.submit(student_id=f'TEST{i:04}',nickname=f'Player{i}',elapsed_ms=30000+i*1000)
        top=self.board()['top'];self.assertEqual(len(top),10);self.assertEqual(top[0]['nickname'],'Player0');self.assertEqual(top[-1]['rank'],10)
        _,r=self.submit(student_id='TESTLAST',elapsed_ms=100000);self.assertIsNone(r['rank'])
    def test_concurrent_writes(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda i:self.submit(student_id=f'CONCURRENT{i:04}',nickname=f'Racer{i}')[0],range(12)))
        self.assertEqual(results,[200]*12)
        self.assertEqual(len((self.data/'results.jsonl').read_text().splitlines()),12)
    def test_partial_last_line_recovery(self):
        self.submit()
        with (self.data/'results.jsonl').open('ab') as f:f.write(b'{"v":')
        self.stop();self.start();self.submit(student_id='SECOND123',nickname='Second')
        self.stop();self.start();self.assertEqual(self.board()['runs_today'],2)
    def test_sentences(self):
        raw=(SHARE/'sentences.js').read_text();rows=json.loads(raw.split('/* SENTENCES_START */')[1].split('/* SENTENCES_END */')[0])
        self.assertGreaterEqual(len(rows),60);self.assertEqual(len({r['id'] for r in rows}),len(rows))
        topics={}
        for row in rows:
            text=row['text'];self.assertTrue(text.isascii());self.assertTrue(130<=len(text)<=170,(row['id'],len(text)))
            self.assertTrue(22<=len(text.split())<=28,(row['id'],len(text.split())))
            topics[row['topic']]=topics.get(row['topic'],0)+1
        self.assertEqual(sorted(topics.items()),[('booths',40),('carnival',20),('chess',20),('computer',20)])
    def test_launcher_server_only_and_single_instance(self):
        env=dict(os.environ,TYPING_CONTEST_DATA=str(self.base/'launch'),TYPING_CONTEST_SHARE=str(SHARE),TYPING_CONTEST_TEACHER_KEY=str(self.key),TYPING_CONTEST_NO_BROWSER='1',PYTHONDONTWRITEBYTECODE='1')
        command=[sys.executable,'-I',str(ROOT/'files/usr/local/bin/typing-contest')]
        proc=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            import select
            self.assertTrue(select.select([proc.stdout],[],[],10)[0]);url=proc.stdout.readline().strip();self.assertTrue(url.startswith('http://127.0.0.1:'))
            second=subprocess.run(command,env=env,capture_output=True,text=True,timeout=15);self.assertEqual(second.returncode,0,second.stderr);self.assertEqual(second.stdout.strip(),url)
            exported=subprocess.run(command+['--export',str(self.base/'export')],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(exported.returncode,0,exported.stderr);self.assertTrue(Path(exported.stdout.strip()).exists())
        finally:
            proc.send_signal(signal.SIGTERM);proc.communicate(timeout=10)
        self.assertFalse((self.base/'launch/run.json').exists())

    def check(self,**kw):
        status,body,_=self.request('/api/check',kw);return status,json.loads(body)
    def test_nickname_locked_to_id(self):
        # A new ID needs a nickname; afterwards the ID keeps it on this laptop.
        self.assertEqual(self.check(student_id='SYNTHETIC111')[0],400)
        status,r=self.check(student_id='SYNTHETIC111',nickname='Knight');self.assertEqual((status,r['nickname'],r['returning']),(200,'Knight',False))
        self.assertEqual(self.submit(student_id='SYNTHETIC111',nickname='Knight')[1]['nickname'],'Knight')
        status,r=self.check(student_id='syn thetic111',nickname='');self.assertEqual((r['nickname'],r['returning']),('Knight',True))
        status,r=self.check(student_id='SYNTHETIC111',nickname='Other');self.assertEqual(r['nickname'],'Knight')
        status,r=self.submit(student_id='SYNTHETIC111',nickname='Other');self.assertEqual(status,200);self.assertEqual(r['nickname'],'Knight')
        # A nickname belongs to one ID (case-insensitive).
        status,r=self.check(student_id='SYNTHETIC222',nickname='knight');self.assertEqual(status,400);self.assertIn('taken',r['error'])
        self.assertEqual(self.submit(student_id='SYNTHETIC222',nickname='KNIGHT')[0],400)
        self.assertEqual(self.submit(student_id='SYNTHETIC222',nickname='Bishop')[0],200)
        self.assertEqual({row['nickname'] for row in self.board()['top']},{'Knight','Bishop'})
        # The lock survives a restart.
        self.stop();self.start()
        self.assertEqual(self.check(student_id='SYNTHETIC111')[1]['nickname'],'Knight')
    def test_old_runs_with_two_nicknames_show_the_first(self):
        self.submit(student_id='SYNTHETIC333',nickname='Pawn')
        with (self.data/'results.jsonl').open() as f:row=json.loads(f.readline())
        row.update(nickname='Queen',wpm=99.0)
        with (self.data/'results.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        self.stop();self.start()
        self.assertEqual([r['nickname'] for r in self.board()['top']],['Pawn'])
    def test_booth_sentences(self):
        booths=[s for s in self.http.store.sentences if s.startswith('booth-')]
        self.assertGreaterEqual(len(booths),40)
    def test_full_results(self):
        # Everyone is listed: qualified players first, then the rest by their best run.
        self.submit(student_id='SYNTHETIC10001',nickname='Fast',elapsed_ms=20000)
        self.submit(student_id='SYNTHETIC10002',nickname='Slow',elapsed_ms=60000)
        n=self.run_data()['typed_chars']
        self.submit(student_id='SYNTHETIC10003',nickname='Sloppy',elapsed_ms=10000,total_keys=n*2)
        self.submit(student_id='SYNTHETIC10002',elapsed_ms=40000)
        status,body,_=self.request('/api/results');self.assertEqual(status,200);data=json.loads(body)
        self.assertEqual([(p['rank'],p['nickname'],p['qualified'],p['runs']) for p in data['players']],
                         [(1,'Fast',True,1),(2,'Slow',True,2),(3,'Sloppy',False,1)])
        self.assertEqual(data['players'][1]['wpm'],round(n*12000/40000,1))
        self.assertEqual(data['players'][0]['id_hint'],'•••10001');self.assertEqual(data['runs'],4)
        self.assertNotIn(b'SYNTHETIC',body)

if __name__=='__main__':unittest.main(verbosity=2)
