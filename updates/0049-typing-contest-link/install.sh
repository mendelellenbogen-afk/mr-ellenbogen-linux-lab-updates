#!/bin/bash
# 0049-typing-contest-link (2026-10-27; the teacher's request: merge the booth laptops'
# results over Wi-Fi)
# Speed Typing Contest: "Booth link" (bottom of the screen). One booth laptop makes a booth
# code (ABCD-EFGH-JKMN); the others type it. Linked laptops share every run made while
# linked, encrypted with a key made from the code (AES-GCM), through the lab message server
# (ntfy.sh as the fallback, read less often), so the Top 10, Full results and nickname lock
# cover all of them. Only laptops with the code can read or add runs. Works offline as
# before; runs wait and are sent when the laptop is back online. Runs made before linking
# stay on their own laptop.
# Small prize (teacher, 2026-10-27): a run with 90 %+ accuracy that places in the top 10 % of
# everyone who has played so far (across linked laptops) shows a prize animation, once per
# student; Full results marks who won one. The top 3 at the end win the big prizes.
# Reinstalls the same files as 0048 (server.py, app.js,
# index.html, style.css, the launcher's --export changed). Safe to re-run.
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
say "Speed Typing Contest updated: Booth link (app menu: search \"typing\")"
