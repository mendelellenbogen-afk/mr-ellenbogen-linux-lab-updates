#!/bin/bash
# 0056-typing-contest-score (2026-11-04; the teacher's choice after the booth practice run)
# Speed Typing Contest ranks by SCORE = WPM x accuracy x accuracy, so speed and accuracy both
# count (each 1 % of accuracy is worth about 2 % of speed); a finished run needs 70 %+ accuracy
# to make the board (was 90 %). The Top 10, Full results, candy (top half, every race, as in
# 0054) and personal bests all use the score; runs saved under 0054 are re-scored.
# Still closes at 12:20 PM Nov 6 when linked (0054). Same files as 0054 (server.py, app.js,
# index.html changed). Safe to re-run.
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
say "Speed Typing Contest updated for the carnival (score = WPM x accuracy x accuracy, 70 %+ accuracy) (app menu: search \"typing\")"
