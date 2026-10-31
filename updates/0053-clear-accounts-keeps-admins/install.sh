#!/bin/bash
# 0053-clear-accounts-keeps-admins
# Teacher's request 2026-10-30: the login screen's "Admin: clear student
# accounts" (0050) must not delete a colleague's admin account. It now also
# keeps every account in the sudo group (admin accounts), besides
# administrator, StudentTest1 and StudentTest2. No names here: the admin
# accounts come from the sudo group on each laptop.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

LIB=/usr/local/lib/school-account

install_file files$LIB/clear_accounts.py $LIB/clear_accounts.py 644
rm -rf $LIB/__pycache__

# The service imports clear_accounts.py once at start: restart it to use the new rule.
systemctl restart school-clear-accounts.service || say "could not restart school-clear-accounts (it uses the new rule at the next restart)"
say "done"
