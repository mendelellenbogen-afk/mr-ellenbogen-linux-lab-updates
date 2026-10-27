#!/bin/bash
# 0048-typing-contest-booths (2026-10-27; the teacher's requests after 0047)
# Speed Typing Contest (0047), three changes:
#  * A student ID keeps the first nickname it used on this laptop (returning players
#    can leave the nickname empty; "Welcome back, <nickname>!"), and a nickname belongs
#    to one ID. Checked by the local server before the race and again when saving.
#  * 40 new sentences about the carnival's other booths (100 in all).
#  * "Full results" button: every player on this laptop ranked (90 %+ first), with the
#    last 5 digits of the ID (was 4; runs saved by 0047 keep 4), Print / Save as PDF,
#    so the booth students can view and collect the final results without the teacher.
# Reinstalls the same files as 0047 (server.py, app.js, index.html, style.css and
# sentences.js changed). Results from 0047 are kept and work unchanged. Safe to re-run.
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
say "Speed Typing Contest updated (app menu: search \"typing\")"
