#!/bin/bash
# 0050-typing-contest-qr (2026-10-27; the teacher's request)
# Speed Typing Contest: while the laptop is linked to a booth (Booth link, 0049), a QR code
# under the Top 10 opens the live Top 10 page for phones
# (https://claude.ai/artifact/9ieAfDe4qepHyc8SLrUDAU, kept up to date from the teacher's
# computer during the carnival). The QR code is a static picture (live-qr.svg), made on
# the teacher's computer; the laptops stay offline-capable. Otherwise the same files as
# 0049 (server.py serves the picture; app.js, index.html, style.css show it). Safe to re-run.
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
say "Speed Typing Contest updated: live Top 10 QR code (app menu: search \"typing\")"
