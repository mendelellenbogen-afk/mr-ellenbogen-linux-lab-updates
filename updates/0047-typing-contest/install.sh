#!/bin/bash
# 0047-typing-contest (2026-10-27; the teacher's request for the school carnival day)
# "Speed Typing Contest" in the app menu (search "typing"): a typeracer-style race of one
# ~30-second sentence about chess, computer science or carnivals. The student types a
# student ID + nickname; the laptop's own Top 10 (each student's best run with >= 90 %
# accuracy, unlimited tries) shows the nickname and the last 4 characters of the ID.
# Fully offline: a small server on 127.0.0.1 in the user's own session, shown in a
# Chrome app window (0031). Results stay in that account's ~/.local/share/typing-contest/
# (0600); the full student ID is stored only encrypted to the teacher's key (0022).
# `typing-contest --export DIR` copies the results for the teacher's
# tools/typing-contest-results. No service, nothing runs until someone opens it.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/bin/typing-contest                 /usr/local/bin/typing-contest 755
install_file files/usr/local/lib/typing-contest/server.py       /usr/local/lib/typing-contest/server.py 644
for page in index.html style.css app.js sentences.js; do
    install_file "files/usr/local/share/typing-contest/$page"   "/usr/local/share/typing-contest/$page" 644
done
install_file files/usr/local/share/applications/typing-contest.desktop /usr/local/share/applications/typing-contest.desktop 644

[ -x /usr/bin/google-chrome ] || say "Chrome is missing (0031): the contest opens in the default browser instead"
[ -f /etc/lab-inventory/teacher-key.pub.pem ] || say "teacher key missing (0022): student IDs won't be saved for the teacher"
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/local/share/applications || true
say "Speed Typing Contest installed (app menu: search \"typing\")"
