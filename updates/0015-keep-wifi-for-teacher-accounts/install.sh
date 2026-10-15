#!/bin/bash
# 0015-keep-wifi-for-teacher-accounts
# Wi-Fi joined while ONLY Administrator / StudentTest1 / StudentTest2 are
# logged in is remembered, shared by those three accounts, and connects
# automatically when one of them logs in (the user's choice, 2026-10-14).
# Everyone else's Wi-Fi is still forgotten at logout / suspend / shutdown,
# and the remembered networks never connect at the login screen or for
# students (NetworkManager connection.permissions). prepare-image.sh uses
# "school-forget-wifi --all", so remembered networks never reach an image.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/etc/school-account/wifi-keep-accounts /etc/school-account/wifi-keep-accounts 644
# Forget script first: it honours the skip file, so restarting the watcher
# below (whose stop step runs the forget script) doesn't drop the current Wi-Fi.
install_file files/usr/local/sbin/school-forget-wifi       /usr/local/sbin/school-forget-wifi 755
install_file files/usr/local/sbin/school-forget-wifi-watch /usr/local/sbin/school-forget-wifi-watch 755
touch /run/school-forget-wifi.skip
systemctl restart school-forget-wifi.service
rm -f /run/school-forget-wifi.skip

# Remember the network in use right now, if a teacher/test account is logged in.
/usr/local/sbin/school-forget-wifi --claim-only
say "done"
