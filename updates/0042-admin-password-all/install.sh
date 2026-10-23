#!/bin/bash
# 0042-admin-password-all (the teacher's decision, 2026-10-23): change the
# administrator password on EVERY laptop. 0041 set it on lab-5cd137htq8 first;
# the teacher confirmed there: the new password works and the old one does not.
# Why: a student is stress-testing a lab laptop at home (with permission) and
# every laptop came from one image with the same administrator password.
# Only the password's SHA-512 hash is here (this repo is public); the teacher
# made it on their own computer and never shared the password.
# Safe to re-run: sets the hash only if it isn't already set.
source "$LAB_UPDATER_HELPERS"

NEW_HASH='$6$hKlY3/bR6sRg5Hpd$1MwmcclGmtnUjq/.XPiOhkQ2kuBzR3G671G8GP4MUtMikT/OT8FbN/X07QjY1xD/cAJyDz/U6cHIh7t9X.CIK.'

if ! getent passwd administrator >/dev/null; then
    say "no administrator account on this laptop; nothing to do"
    exit 0
fi
if [ "$(getent shadow administrator | cut -d: -f2)" = "$NEW_HASH" ]; then
    say "administrator password already the new one"
    exit 0
fi
usermod -p "$NEW_HASH" administrator
if [ "$(getent shadow administrator | cut -d: -f2)" != "$NEW_HASH" ]; then
    say "the new administrator password didn't take"
    exit 1
fi
say "administrator password changed"
