#!/bin/bash
# 0051-typing-contest-carnival (2026-10-27; the teacher's requests for the carnival, Nov 6)
# Speed Typing Contest:
#  * Booth screens show the last 4 characters of the student ID (was 5; the live page
#    shows no IDs at all).
#  * No "Make a new booth code" button: booth codes are made on the teacher's computer
#    (tools/typing-contest-board --new-code) and typed in under Booth link, so a booth
#    runner can't split the booth off the live page.
#  * A linked laptop's board shows only the races of its current booth code; a new code
#    starts a fresh board (test races never reach the carnival). Unlinked, it shows the
#    races made unlinked.
# Otherwise the same files as 0050 (server.py, app.js, index.html changed). Safe to re-run.
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
say "Speed Typing Contest updated for the carnival (app menu: search \"typing\")"
