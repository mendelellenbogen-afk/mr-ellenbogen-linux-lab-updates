#!/usr/bin/env python3
"""Tests for 0010-identical-test-accounts (lab-reset-test-accounts).

The account tools (adduser, userdel, usermod, chpasswd, getent, id, loginctl,
pgrep, ...) are replaced by fake_account_tools.py over a JSON user database;
/home and /var/lib/AccountsService are temp folders (unshare -r -m). No root.

    python3 -I update-repo/tests/test_0010_test_accounts.py
"""

import json, os, shutil, subprocess, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "updates", "0010-identical-test-accounts", "files",
                      "usr", "local", "sbin", "lab-reset-test-accounts")
TOOLS = ("getent", "id", "loginctl", "pgrep", "userdel", "groupdel", "adduser", "usermod", "chpasswd", "chown")

def base_db():
    return {"users": {
        "administrator": {"uid": 1000, "gecos": "Administrator", "hash": "$y$ADMIN"},
        "teststudent": {"uid": 1001, "gecos": ",,,", "hash": "$y$HASHONE"},
        "studenttwo": {"uid": 1003, "gecos": "", "hash": "$y$HASHTWO"},
        "tdsb-123456789": {"uid": 1004, "gecos": "123456789", "hash": "$y$T"}},
     "groups": {"users": {"gid": 100, "members": ["administrator", "teststudent", "studenttwo", "tdsb-123456789"]},
                "dialout": {"gid": 20, "members": ["teststudent"]},
                **{n: {"gid": g, "members": []} for n, g in [("administrator",1000),("teststudent",1001),("studenttwo",1003),("tdsb-123456789",1004)]}}}

class Reset(unittest.TestCase):
    def setUp(self):
        # Not under /home: that gets replaced inside the namespace.
        self.t = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp"))
        self.stubs = os.path.join(self.t, "stubs"); os.makedirs(self.stubs)
        shutil.copy(os.path.join(HERE, "fake_account_tools.py"), os.path.join(self.stubs, "fake.py"))
        for tool in TOOLS:
            os.symlink("fake.py", os.path.join(self.stubs, tool))
        self.script = os.path.join(self.t, "lab-reset-test-accounts")
        shutil.copy(SOURCE, self.script)
        self.home = os.path.join(self.t, "home"); self.state = os.path.join(self.t, "state")
        for n in ("administrator", "teststudent", "studenttwo", "tdsb-123456789"):
            os.makedirs(os.path.join(self.home, n))
        os.makedirs(os.path.join(self.home, "teststudent", "IdeaProjects", "demo"))
        self.dbp = os.path.join(self.t, "db.json"); self.write(base_db())
    def tearDown(self): shutil.rmtree(self.t)
    def write(self, db):
        with open(self.dbp, "w") as f: json.dump(db, f)
    def db(self):
        with open(self.dbp) as f: return json.load(f)
    def run_reset(self):
        inner = f"mkdir -p {self.t}/acc/users && mount --bind {self.t}/acc /var/lib/AccountsService && mount --bind {self.home} /home && exec bash {self.script}"
        env = dict(os.environ, PATH=self.stubs + ":" + os.environ["PATH"],
                   FAKEDB=self.dbp, LAB_TEST_ACCOUNTS_STATE=self.state)
        r = subprocess.run(["unshare", "-r", "-m", "bash", "-c", inner], env=env, capture_output=True, text=True)
        self.out = r.stdout + r.stderr
        return r.returncode
    def calls(self):
        try:
            with open(self.dbp + ".log") as f: return f.read()
        except FileNotFoundError: return ""
    def check_ready(self, db, name, label, h):
        u = db["users"][name]
        self.assertEqual(u["gecos"], label); self.assertEqual(u["hash"], h)
        for g in ("users", "dialout"): self.assertIn(name, db["groups"][g]["members"])
        for f in ("Python", "Java", "C++", "JavaFX"):
            self.assertTrue(os.path.isdir(os.path.join(self.home, name, "CS", f)))
        self.assertTrue(os.path.exists(os.path.join(self.state, name + ".done")))
        self.assertFalse(os.path.exists(os.path.join(self.state, name + ".hash")))

    def test_both_reset(self):
        self.assertEqual(self.run_reset(), 0, self.out)
        db = self.db()
        self.assertNotIn("teststudent", db["users"]); self.assertNotIn("studenttwo", db["users"])
        self.assertNotIn("teststudent", db["groups"]); self.assertNotIn("teststudent", db["groups"]["dialout"]["members"])
        self.check_ready(db, "studenttest1", "StudentTest1", "$y$HASHONE")
        self.check_ready(db, "studenttest2", "StudentTest2", "$y$HASHTWO")
        self.assertEqual(sorted(os.listdir(self.home)), ["administrator", "studenttest1", "studenttest2", "tdsb-123456789"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.home, "studenttest1"))), [".bashrc", "CS"])
        self.assertIn("tdsb-123456789", db["groups"]["dialout"]["members"])
        self.assertNotIn("administrator", db["groups"]["dialout"]["members"])
        self.assertEqual(db["users"]["administrator"]["hash"], "$y$ADMIN")

    def test_rerun_changes_nothing(self):
        self.assertEqual(self.run_reset(), 0, self.out)
        before = self.db(); os.remove(self.dbp + ".log")
        self.assertEqual(self.run_reset(), 0, self.out)
        self.assertEqual(self.db(), before)
        self.assertNotIn("adduser", self.calls()); self.assertNotIn("userdel", self.calls())

    def test_logged_in_waits_then_finishes(self):
        db = base_db(); db["logged_in"] = [1001]; self.write(db)
        self.assertEqual(self.run_reset(), 2, self.out)
        db = self.db()
        self.assertIn("teststudent", db["users"]); self.assertTrue(os.path.isdir(os.path.join(self.home, "teststudent", "IdeaProjects")))
        self.check_ready(db, "studenttest2", "StudentTest2", "$y$HASHTWO")
        db["logged_in"] = []; db["running"] = [1001]; self.write(db)
        self.assertEqual(self.run_reset(), 2, self.out)   # programs still running
        db = self.db(); db["running"] = []; self.write(db)
        self.assertEqual(self.run_reset(), 0, self.out)
        self.check_ready(self.db(), "studenttest1", "StudentTest1", "$y$HASHONE")

    def test_missing_account_gets_partner_password(self):
        db = base_db(); del db["users"]["studenttwo"]; del db["groups"]["studenttwo"]; self.write(db)
        shutil.rmtree(os.path.join(self.home, "studenttwo"))
        self.assertEqual(self.run_reset(), 0, self.out)
        self.check_ready(self.db(), "studenttest2", "StudentTest2", "$y$HASHONE")

    def test_failure_keeps_password_for_retry(self):
        db = base_db(); db["fail_adduser"] = True; self.write(db)
        self.assertEqual(self.run_reset(), 1, self.out)
        self.assertNotIn("studenttest2", self.db()["users"])      # stopped at the first failure
        self.assertEqual(open(os.path.join(self.state, "studenttest1.hash")).read().strip(), "$y$HASHONE")
        db = self.db(); db["fail_adduser"] = False; self.write(db)
        self.assertEqual(self.run_reset(), 0, self.out)
        self.check_ready(self.db(), "studenttest1", "StudentTest1", "$y$HASHONE")
        self.check_ready(self.db(), "studenttest2", "StudentTest2", "$y$HASHTWO")

    def test_already_renamed_account_not_done_is_redone(self):
        # e.g. interrupted right after adduser: studenttest1 exists, no .done
        db = base_db(); db["users"]["studenttest1"] = {"uid": 1010, "gecos": "StudentTest1", "hash": "!"}
        db["groups"]["studenttest1"] = {"gid": 1010, "members": []}; self.write(db)
        os.makedirs(self.state); open(os.path.join(self.state, "studenttest1.hash"), "w").write("$y$HASHONE\n")
        del db["users"]["teststudent"]; del db["groups"]["teststudent"]; self.write(db)
        self.assertEqual(self.run_reset(), 0, self.out)
        self.check_ready(self.db(), "studenttest1", "StudentTest1", "$y$HASHONE")

if __name__ == "__main__":
    unittest.main(verbosity=2)
