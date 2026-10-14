#!/usr/bin/env python3
"""Stand-in for the account tools in test_0010 (run via symlinks named adduser, userdel, ...)."""
import json, os, sys, shutil
db_path = os.environ["FAKEDB"]
db = json.load(open(db_path))
cmd = os.path.basename(sys.argv[0]); args = sys.argv[1:]
with open(db_path + ".log", "a") as log: log.write(cmd + " " + " ".join(args) + "\n")
users, groups = db["users"], db["groups"]
def save(): json.dump(db, open(db_path, "w"), indent=1)
def die(msg, code=1): print(f"{cmd}: {msg}", file=sys.stderr); sys.exit(code)
if cmd == "getent":
    table, key = args[0], (args[1] if len(args) > 1 else None)
    if table == "passwd":
        rows = [f"{n}:x:{u['uid']}:{u['uid']}:{u['gecos']}:/home/{n}:/bin/bash" for n, u in users.items()]
    elif table == "shadow":
        rows = [f"{n}:{u['hash']}:20000:0:99999:7:::" for n, u in users.items()]
    else:
        rows = [f"{g}:x:{v['gid']}:{','.join(v['members'])}" for g, v in groups.items()]
    if key: rows = [r for r in rows if r.split(":")[0] == key]
    if not rows: sys.exit(2)
    print("\n".join(rows))
elif cmd == "id":
    n = args[-1]
    if n not in users: die("no such user")
    if args[0] == "-u": print(users[n]["uid"])
    else: print(" ".join([n] + [g for g, v in groups.items() if n in v["members"]]))
elif cmd == "loginctl":
    for uid in db.get("logged_in", []): print(f"5 {uid} someone seat0 123 user tty2 no -")
elif cmd == "pgrep":
    sys.exit(0 if int(args[-1]) in db.get("running", []) else 1)
elif cmd == "userdel":
    n = args[-1]
    if n not in users: die("user does not exist", 6)
    if users[n]["uid"] in db.get("logged_in", []): die("user is logged in", 8)
    del users[n]
    if n in groups: del groups[n]
    for v in groups.values():
        if n in v["members"]: v["members"].remove(n)
    if "--remove" in args: shutil.rmtree(f"/home/{n}", ignore_errors=True)
    save()
elif cmd == "groupdel":
    if args[-1] not in groups: die("group does not exist", 6)
    del groups[args[-1]]; save()
elif cmd == "adduser":
    n = args[-1]; gecos = args[args.index("--comment") + 1]
    if n in users: die("user exists")
    if n in groups: die("group exists")
    uid = max(u["uid"] for u in users.values()) + 1
    if db.get("fail_adduser"): die("simulated failure")
    users[n] = {"uid": uid, "gecos": gecos, "hash": "!"}
    groups[n] = {"gid": uid, "members": []}
    os.makedirs(f"/home/{n}"); open(f"/home/{n}/.bashrc", "w").write("skel\n")
    save()
elif cmd == "usermod":
    assert args[0] == "-aG"; n = args[2]
    for g in args[1].split(","):
        if n not in groups[g]["members"]: groups[g]["members"].append(n)
    save()
elif cmd == "chpasswd":
    assert args == ["-e"]
    for line in sys.stdin:
        n, h = line.rstrip("\n").split(":", 1); users[n]["hash"] = h
    save()
elif cmd == "chown":
    pass
else:
    die("unknown")
