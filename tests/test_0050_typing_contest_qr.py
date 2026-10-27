#!/usr/bin/env python3
"""Tests for 0050-typing-contest-qr (server, store, page files, sentences, and two booth
laptops linked through a private local ntfy server). Loopback, temp data, synthetic IDs.

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
ROOT=Path(__file__).resolve().parents[1]/'updates'/'0050-typing-contest-qr'
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
        self.http=server.create_server(self.data,SHARE,self.key,sync=False)
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
        for path in ('/','/index.html','/style.css','/app.js','/sentences.js','/live-qr.svg'):
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
    def test_small_prize_top_ten_percent_once(self):
        n=self.run_data()['typed_chars']
        ms=lambda wpm:int(n*12000/wpm)
        r=self.submit(student_id='SYNTHETIC20001',nickname='First',elapsed_ms=ms(40))[1]
        self.assertTrue(r['small_prize'])                          # 1 player: top 10 % = 1st
        r=self.submit(student_id='SYNTHETIC20002',nickname='Second',elapsed_ms=ms(30))[1]
        self.assertFalse(r['small_prize']);self.assertFalse(r['prize_already'])
        r=self.submit(student_id='SYNTHETIC20002',elapsed_ms=ms(50))[1]
        self.assertTrue(r['small_prize'])                          # new leader
        r=self.submit(student_id='SYNTHETIC20002',elapsed_ms=ms(60))[1]
        self.assertFalse(r['small_prize']);self.assertTrue(r['prize_already'])   # once each
        r=self.submit(student_id='SYNTHETIC20003',nickname='Sloppy',elapsed_ms=ms(90),total_keys=n*2)[1]
        self.assertFalse(r['small_prize'])                         # below 90 %: no prize
        for i in range(4,12): self.submit(student_id=f'SYNTHETIC2{i:04}',nickname=f'P{i}',elapsed_ms=ms(20))
        r=self.submit(student_id='SYNTHETIC29999',nickname='Late',elapsed_ms=ms(45))[1]
        self.assertTrue(r['small_prize'])                          # 12 players: top 2; 2nd place
        r=self.submit(student_id='SYNTHETIC29998',nickname='Later',elapsed_ms=ms(44))[1]
        self.assertFalse(r['small_prize'])                         # 13 players: top 2; 3rd place
        prized={p['nickname'] for p in json.loads(self.request('/api/results')[1])['players'] if p['small_prize']}
        self.assertEqual(prized,{'First','Second','Late'})
    def test_live_qr_code(self):
        status,body,headers=self.request('/live-qr.svg')
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'image/svg+xml');self.assertTrue(body.startswith(b'<svg'))
        self.assertNotIn(b'<script',body.lower())
        page=self.request('/')[1];self.assertIn(b'id="live-qr" hidden',page);self.assertIn(b'claude.ai/artifact/9ieAfDe4qepHyc8SLrUDAU',page)
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

def free_port():
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0)); return probe.getsockname()[1]

@unittest.skipUnless(__import__('shutil').which('ntfy'),'needs ntfy')
class BoothLinkTests(unittest.TestCase):
    """Two (or three) laptops: separate data folders, one private ntfy, sync rounds run by hand."""
    @classmethod
    def setUpClass(cls):
        cls.private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.dir=Path(tempfile.mkdtemp());cls.port=free_port()
        (cls.dir/'server.yml').write_text(f"listen-http: 127.0.0.1:{cls.port}\ncache-file: {cls.dir}/cache.db\ncache-duration: 1h\n"
            "visitor-request-limit-burst: 100000\nvisitor-request-limit-replenish: 1ms\nvisitor-message-daily-limit: 0\n")
        cls.ntfy=subprocess.Popen(['ntfy','serve','-c',str(cls.dir/'server.yml')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        import socket,time
        for _ in range(100):
            try: socket.create_connection(('127.0.0.1',cls.port),timeout=0.2).close();break
            except OSError: time.sleep(0.1)
        cls.key=cls.dir/'teacher.pem';cls.key.write_bytes(cls.private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    @classmethod
    def tearDownClass(cls):
        cls.ntfy.terminate();cls.ntfy.wait()
    def laptop(self,name,servers=None):
        os.environ['TYPING_CONTEST_SERVERS']=servers or f'http://127.0.0.1:{self.port}'
        os.environ['TYPING_CONTEST_HOSTNAME']=name
        data=Path(tempfile.mkdtemp(dir=self.dir))/'data'
        return server.Store(data,SHARE,self.key)
    def run_for(self,store,sid,nickname='',**kw):
        sentence=next(iter(store.sentences));n=len(store.sentences[sentence])
        value=dict(student_id=sid,nickname=nickname,sentence_id=sentence,typed_chars=n,correct_keys=n,total_keys=n,elapsed_ms=30000,finished=True);value.update(kw)
        return store.submit(value)
    def test_two_laptops_share_one_board(self):
        a,b=self.laptop('lab-aaa'),self.laptop('lab-bbb')
        code=a.booth.change({'action':'create'})['code'];self.assertRegex(code,r'^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$')
        self.assertEqual(b.booth.change({'action':'join','code':code.lower().replace('-',' ')})['code'],code)
        self.run_for(a,'SYNTHETIC70001','Ada',elapsed_ms=20000)
        self.run_for(b,'SYNTHETIC70002','Babbage',elapsed_ms=40000)
        for store in (a,b,a,b): store.booth.sync()
        for store in (a,b):
            self.assertEqual([r['nickname'] for r in store.board()['top']],['Ada','Babbage'])
            st=store.booth.status();self.assertEqual((st['laptops'],st['pending'],st['error']),(2,0,''))
            self.assertIsNotNone(st['last_ok'])
        # The same student on the other laptop: same nickname, best run counts once.
        self.assertEqual(b.check({'student_id':'SYNTHETIC70001'})['nickname'],'Ada')
        self.assertEqual(self.run_for(b,'SYNTHETIC70001','Other',elapsed_ms=15000)['nickname'],'Ada')
        with self.assertRaises(ValueError): b.check({'student_id':'SYNTHETIC70003','nickname':'ada'})
        b.booth.sync();a.booth.sync()
        players=a.results()['players']
        self.assertEqual([(p['nickname'],p['runs']) for p in players],[('Ada',2),('Babbage',1)])
        self.assertEqual(players[0]['wpm'],b.results()['players'][0]['wpm'])
        # Restart: the other laptop's runs are kept, nothing is sent twice.
        a2=server.Store(a.data,SHARE,self.key);self.assertEqual(len(a2.results()['players']),2)
        self.assertEqual(a2.booth.status()['pending'],0)
    def test_wrong_code_reads_nothing_and_leave_clears(self):
        a,c=self.laptop('lab-ccc'),self.laptop('lab-ddd')
        a.booth.change({'action':'create'});c.booth.change({'action':'create'})
        self.run_for(a,'SYNTHETIC80001','Turing');a.booth.sync();c.booth.sync()
        self.assertEqual(c.results()['players'],[])
        # Messages on the topic are encrypted: no nickname or ID in the clear.
        import urllib.request
        raw=urllib.request.urlopen(f'http://127.0.0.1:{self.port}/{a.booth.topic}/json?poll=1&since=all').read()
        self.assertNotIn(b'Turing',raw);self.assertNotIn(b'SYNTHETIC',raw);self.assertIn(b'mrellenbogen-lab-typing-',raw)
        with self.assertRaises(ValueError): a.booth.change({'action':'join','code':'nope'})
        a.booth.change({'action':'leave'});self.assertFalse(a.booth.status()['linked'])
        self.assertFalse((a.data/'booth.json').exists())
        self.assertEqual([p['nickname'] for p in a.results()['players']],['Turing'])
    def test_late_laptop_and_offline_retry(self):
        a=self.laptop('lab-eee',servers='http://127.0.0.1:9')   # nothing listens: offline
        code=a.booth.change({'action':'create'})['code']
        self.run_for(a,'SYNTHETIC90001','Hopper');a.booth.sync()
        st=a.booth.status();self.assertEqual(st['pending'],1);self.assertIn('could not send',st['error'])
        a.booth.servers=[f'http://127.0.0.1:{self.port}'];a.booth.sync()
        self.assertEqual(a.booth.status()['pending'],0)
        late=self.laptop('lab-fff');late.booth.change({'action':'join','code':code});late.booth.sync()
        self.assertEqual([p['nickname'] for p in late.results()['players']],['Hopper'])
    def test_small_prize_once_across_linked_laptops(self):
        a,b=self.laptop('lab-hhh'),self.laptop('lab-iii')
        code=a.booth.change({'action':'create'})['code'];b.booth.change({'action':'join','code':code})
        self.assertTrue(self.run_for(a,'SYNTHETIC60001','Grace')['small_prize'])
        a.booth.sync();b.booth.sync()
        r=self.run_for(b,'SYNTHETIC60001',elapsed_ms=20000)
        self.assertFalse(r['small_prize']);self.assertTrue(r['prize_already'])
    def test_bad_remote_rows_are_ignored(self):
        a=self.laptop('lab-ggg');code=a.booth.change({'action':'create'})['code']
        import urllib.request
        def post(row):
            nonce=os.urandom(12);body=json.dumps({'tc':1,'n':base64.b64encode(nonce).decode(),'d':base64.b64encode(a.booth.aead.encrypt(nonce,json.dumps(row).encode(),a.booth.topic.encode())).decode()})
            urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{self.port}/{a.booth.topic}',data=body.encode(),method='POST')).read()
        good=dict(v=1,run_id='ab'*8,bplayer='c'*64,player='d'*64,laptop='e'*12,nickname='Lovelace',id_hint='•••12345',time='2026-10-27T10:00:00-04:00',sentence_id='chess-01',finished=True,wpm=50.0,accuracy=95.0,enc_id=None,qualifies=True)
        post(dict(good,wpm=999,run_id='01'*8));post(dict(good,nickname='<b>x</b>',run_id='02'*8));post({'v':1});post(good)
        urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{self.port}/{a.booth.topic}',data=b'not json',method='POST')).read()
        a.booth.sync()
        self.assertEqual([p['nickname'] for p in a.results()['players']],['Lovelace'])

if __name__=='__main__':unittest.main(verbosity=2)
