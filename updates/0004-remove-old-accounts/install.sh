#!/bin/bash
# 0004-remove-old-accounts
# Deletes every old-style student account (made with the old free-form panel)
# immediately. Anyone logged in is deleted right after they log out.
#
# Never removed: TDSB accounts (tdsb-<ID>, students and staff), accounts in
# /etc/school-account/keep-accounts (administrator, teststudent, studenttwo),
# system accounts, and any account created after this update ran.
source "$LAB_UPDATER_HELPERS"

LIB=/usr/local/lib/school-account

install_file files/etc/school-account/keep-accounts /etc/school-account/keep-accounts 644
install_file files$LIB/legacy_accounts.py         $LIB/legacy_accounts.py 644
install_file files$LIB/legacy-account-cleanup.py  $LIB/legacy-account-cleanup.py 755
install_file files/etc/systemd/system/school-legacy-account-cleanup.service /etc/systemd/system/school-legacy-account-cleanup.service 644
install_file files/etc/systemd/system/school-legacy-account-cleanup.timer   /etc/systemd/system/school-legacy-account-cleanup.timer 644
install -d -o root -g root -m 755 /var/lib/school-account

# Record which accounts are old-style RIGHT NOW (first run only).
say "old-style accounts to remove:"
python3 -c 'import sys; sys.path.insert(0, "/usr/local/lib/school-account"); import legacy_accounts as l; print("  " + (", ".join(n for n, _ in l.snapshot_remove_list()) or "(none)"))'

systemctl daemon-reload
systemctl enable school-legacy-account-cleanup.timer
systemctl start school-legacy-account-cleanup.timer

# Remove them now (logged-in ones go right after logout).
python3 -u $LIB/legacy-account-cleanup.py
