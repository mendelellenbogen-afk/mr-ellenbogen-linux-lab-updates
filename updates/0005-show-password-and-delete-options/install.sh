#!/bin/bash
# 0005-show-password-and-delete-options
#  * Login screen account panel: the password field gets the same eye button as
#    GNOME's own login, to show/hide what was typed (St.PasswordEntry).
#  * Delete My Account: choose "Delete in 7 days" (keep using the account until
#    then) or "Delete now" (logged out, removed right away as before).
#    7-day requests are kept in /var/lib/school-account/self-delete-scheduled/
#    so they survive reboots.
#
# Safe to re-run. The login panel change shows the next time the login screen
# starts (after a logout).
source "$LAB_UPDATER_HELPERS"

SELF_DELETE=/usr/local/lib/school-account/self-delete

install_file files/usr/share/gnome-shell/extensions/school-account@school.local/extension.js \
             /usr/share/gnome-shell/extensions/school-account@school.local/extension.js 644
install_file files$SELF_DELETE/self-delete-service.py     $SELF_DELETE/self-delete-service.py 755
install_file files$SELF_DELETE/self-delete-worker.py      $SELF_DELETE/self-delete-worker.py 755
install_file files$SELF_DELETE/gui/delete-my-account.py   $SELF_DELETE/gui/delete-my-account.py 755
rm -rf $SELF_DELETE/__pycache__ $SELF_DELETE/gui/__pycache__

install -d -o root -g root -m 700 /var/lib/school-account/self-delete-scheduled

# Pending "delete now" requests live in /run and survive these restarts.
systemctl restart school-student-self-delete.service
systemctl restart school-student-self-delete-worker.service

say "done"
