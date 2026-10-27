#!/bin/bash
# 0050-clear-student-accounts
# Teacher's request 2026-10-27: a button on the login screen that, with the
# administrator password, clears every account from the laptop except
# administrator, StudentTest1 and StudentTest2.
#  * Login screen: a small "Admin: clear student accounts" button under the
#    TDSB panel (always visible; does nothing without the password). After the
#    password it shows how many accounts would go, and a red "Delete them"
#    button deletes them (no typing; the teacher's choice).
#  * Logged-in students are logged out first (unsaved work is lost; the
#    teacher's choice). Their home folders are deleted with the accounts.
#  * Root service school-clear-accounts.service (D-Bus com.school.ClearAccounts),
#    callable only from the login screen (polkit) and only with the
#    administrator password; 5 wrong passwords lock it for 5 minutes.
#
# Safe to re-run. The button shows the next time the login screen starts
# (after a logout or restart).
source "$LAB_UPDATER_HELPERS"

LIB=/usr/local/lib/school-account

python3 -c 'import dbus, gi' || { say "STOP: python3-dbus / python3-gi missing"; exit 1; }

install_file files$LIB/clear_accounts.py                            $LIB/clear_accounts.py 644
install_file files$LIB/clear-accounts-service.py                    $LIB/clear-accounts-service.py 755
rm -rf $LIB/__pycache__
install_file files/etc/dbus-1/system.d/com.school.ClearAccounts.conf /etc/dbus-1/system.d/com.school.ClearAccounts.conf 644
install_file files/usr/share/polkit-1/actions/com.school.clear-accounts.policy \
             /usr/share/polkit-1/actions/com.school.clear-accounts.policy 644
install_file files/etc/polkit-1/rules.d/31-school-clear-accounts.rules /etc/polkit-1/rules.d/31-school-clear-accounts.rules 644
install_file files/etc/systemd/system/school-clear-accounts.service  /etc/systemd/system/school-clear-accounts.service 644
install_file files/usr/share/gnome-shell/extensions/school-account@school.local/extension.js \
             /usr/share/gnome-shell/extensions/school-account@school.local/extension.js 644

# The bus normally sees the new policy file by itself; reload to be sure.
systemctl reload dbus.service || say "could not reload D-Bus (it picks up the policy at the next restart)"
systemctl daemon-reload
systemctl enable school-clear-accounts.service
systemctl restart school-clear-accounts.service

say "done (the button shows the next time the login screen starts)"
