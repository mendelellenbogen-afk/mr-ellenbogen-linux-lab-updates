#!/bin/bash
# 0052-private-wifi-for-admins
# The teacher's request (2026-10-29): a colleague's admin account should keep
# its Wi-Fi at logout, for that account only. Every sudo-group account that
# isn't Administrator / StudentTest1 / StudentTest2 now keeps the Wi-Fi it
# joins, restricted to itself (NetworkManager connection.permissions): it
# connects automatically when that account logs in and never for anyone else
# or at the login screen. No names here: the accounts come from the sudo group
# on each laptop. The three shared accounts (0015) and students are unchanged.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

# The watcher runs this script fresh every 2 s, so no restart is needed.
install_file files/usr/local/sbin/school-forget-wifi /usr/local/sbin/school-forget-wifi 755

# Remember the network in use right now, if such an admin is logged in alone.
/usr/local/sbin/school-forget-wifi --claim-only
say "done"
