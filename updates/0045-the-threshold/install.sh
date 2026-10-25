#!/bin/bash
# 0045-the-threshold (2026-10-24; the teacher's class RPG, phase 1)
# The Threshold runs in Chrome, served from the teacher's computer through the
# lab server (https://lab-messages.tail72844f.ts.net/rpg). This update signs
# students in:
#  * lab-rpg.service (root) asks every 20 s, while a student is logged in,
#    whether the teacher has a world running. If so, it asks for a one-time
#    sign-in link for each student, signed with this laptop's own key (from
#    0022's inventory), and opens it in Chrome (0031) as that student, once
#    per session. The teacher's computer only answers for the class that is
#    playing, so other students are left alone.
#  * "The Threshold" in the app menu opens the game again if it was closed.
# Admin accounts are skipped. Nothing is sent while no world is running.
# Needs 0022 (laptop key) and 0031 (Chrome). Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-rpg/lab-rpg-agent.py /usr/local/lib/lab-rpg/lab-rpg-agent.py 755
install_file files/usr/local/bin/the-threshold            /usr/local/bin/the-threshold 755
install_file files/etc/lab-rpg/config                     /etc/lab-rpg/config 644
install_file files/etc/systemd/system/lab-rpg.service     /etc/systemd/system/lab-rpg.service 644
install_file files/usr/local/share/applications/the-threshold.desktop /usr/local/share/applications/the-threshold.desktop 644

[ -x /usr/bin/google-chrome ] || say "Chrome is missing (0031): the game can't open until it is installed"
[ -f /var/lib/lab-inventory/laptop-key ] || systemctl start lab-inventory.service \
    || say "no laptop key yet: sign-in starts working after the next inventory report"

systemctl daemon-reload
systemctl enable lab-rpg.service
systemctl restart lab-rpg.service
say "The Threshold sign-in ready (laptop $(hostname)); idle until the teacher runs a world"
