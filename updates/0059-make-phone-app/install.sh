#!/bin/bash
# 0059-make-phone-app (2026-11-13; build service phase 2 part B, the teacher's choices)
# "Make a Phone App" in the app menu: students pick one of their Java projects
# (~/IdeaProjects, ~/CS/JavaFX, ~/CS/Java), type an app name and the class code from
# the board (remembered per student), and the project is zipped (without target/,
# .idea, .git ...) and sent to the teacher's build service (fx2android-service on the
# lab server address, /apps). The laptop adds the student number and laptop name for
# the teacher's status page. The window shows the place in line, then a QR code to
# scan with a phone and a button that opens the app's page. Nothing runs in the
# background; nothing is set up per account. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/etc/lab-phone-app/config                          /etc/lab-phone-app/config 644
install_file files/usr/local/lib/lab-phone-app/make-phone-app.py     /usr/local/lib/lab-phone-app/make-phone-app.py 755
install_file files/usr/local/share/applications/lab-make-phone-app.desktop /usr/local/share/applications/lab-make-phone-app.desktop 644
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/local/share/applications || true
say "Make a Phone App is in the app menu"
