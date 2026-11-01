#!/bin/bash
# 0054-typing-contest-candy (2026-11-01; the teacher's new rules for the carnival, Fri Nov 6)
# Speed Typing Contest:
#  * Small prize = candy for EVERY race in the top half (50 %) of all players with 90 %+
#    accuracy (was top 10 %, once per student): each retry is paid.
#  * Full results count each player's candies.
#  * A linked booth laptop takes no new races from 12:20 PM on Nov 6 (races started before
#    then get 5 min to finish); unlinking makes it playable again.
# Otherwise the same files as 0051 (server.py, app.js, index.html changed). Safe to re-run.
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
say "Speed Typing Contest updated for the carnival (candy rule, closes 12:20 PM Nov 6) (app menu: search \"typing\")"
