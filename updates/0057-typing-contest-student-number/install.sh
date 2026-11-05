#!/bin/bash
# 0057-typing-contest-student-number (2026-11-05; the teacher's request after a class practice
# where 2 of 16 players raced without a proper student number)
# Speed Typing Contest: only races entered with a 9-digit student number make the Top 10, win
# candy and count as 70 %+ in Full results, because only those winners can be emailed. Other
# IDs can still race; the result says "Not on the board: race with your 9-digit student number".
# The sign-up box now says "Student number (9 digits)". Runs saved before 0057 still count.
# Everything else as 0056 (score = WPM x accuracy x accuracy, 70 %+, closes 12:20 PM Nov 6).
# Same files as 0056 (server.py, app.js, index.html changed). Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/bin/typing-contest                 /usr/local/bin/typing-contest 755
install_file files/usr/local/lib/typing-contest/server.py       /usr/local/lib/typing-contest/server.py 644
for page in index.html style.css app.js sentences.js live-qr.svg; do
    install_file "files/usr/local/share/typing-contest/$page"   "/usr/local/share/typing-contest/$page" 644
done
install_file files/usr/local/share/applications/typing-contest.desktop /usr/local/share/applications/typing-contest.desktop 644

[ -x /usr/bin/google-chrome ] || say "Chrome is missing (0031): the contest opens in the default browser instead"
[ -f /etc/lab-inventory/teacher-key.pub.pem ] || say "teacher key missing (0022): student IDs won't be saved for the teacher"
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/local/share/applications || true
say "Speed Typing Contest updated: only 9-digit student numbers make the board (app menu: search \"typing\")"
