#!/bin/bash
# 0003-tdsb-login  (replaces the withdrawn 0002-tdsb-login)
#  * Login screen: "Login to TDSB to create your account" (student or staff ID +
#    password, checked by joining TDSB-WIFI). IDs are 3-27 letters/digits
#    (students 9 digits, staff 6). Accounts are named "tdsb-"+ID (lowercase)
#    and shown on the login screen as the ID.
#  * "Not listed?" hidden on the login screen.
#  * Login (gdm-password): TDSB accounts get their own TDSB-WIFI connection,
#    and a new school password accepted by TDSB-WIFI updates the laptop's copy.
#  * Wi-Fi is forgotten at LOGOUT (not at login) and on suspend (hook fixed).
#
# Safe to re-run. The login screen panel changes the next time the login screen
# starts (after the current student logs out). No restart is needed.
source "$LAB_UPDATER_HELPERS"

PAM_FILE=/etc/pam.d/gdm-password
PAM_ORIGINAL_SHA=08e1f43267a73fb6f57e58c13332d4d5c9057b3129a528479cc1287712c74ec0
# The withdrawn 0002-tdsb-login left this version (only on the test laptop, if at all):
PAM_0002_SHA=d37638e065f36b79a6dd48d1a9d614443cad102e3d2b08f7ef2f100cd0a8cbbb
PAM_NEW_SHA=$(sha256sum files/etc/pam.d/gdm-password | cut -d' ' -f1)
BACKUP=/var/lib/school-account/backup-tdsb-login
OLD_BACKUP=/var/lib/school-account/backup-0002
PAM_MODULES=/usr/lib/x86_64-linux-gnu/security

# --- Safety checks before changing anything ---------------------------------
current_sha=$(sha256sum "$PAM_FILE" | cut -d' ' -f1)
if [ "$current_sha" != "$PAM_ORIGINAL_SHA" ] && [ "$current_sha" != "$PAM_0002_SHA" ] \
   && [ "$current_sha" != "$PAM_NEW_SHA" ]; then
    say "STOP: $PAM_FILE is not the version this update expects; not touching logins."
    exit 1
fi
for module in pam_unix.so pam_sss.so pam_exec.so pam_deny.so pam_permit.so pam_cap.so; do
    [ -f "$PAM_MODULES/$module" ] || { say "STOP: missing $module"; exit 1; }
done
python3 -c 'import dbus, gi' || { say "STOP: python3-dbus / python3-gi missing"; exit 1; }

# --- Back up what this update replaces (first run only) ---------------------
# If 0002 already ran here, its backup holds the true originals: keep using it.
if [ ! -d "$BACKUP" ] && [ -d "$OLD_BACKUP" ]; then
    cp -a "$OLD_BACKUP" "$BACKUP"
    say "kept the original files backed up by 0002 in $BACKUP"
fi
if [ ! -d "$BACKUP" ]; then
    mkdir -p "$BACKUP"
    for path in \
        "$PAM_FILE" \
        /usr/local/sbin/school-forget-wifi \
        /etc/systemd/system/school-forget-wifi.service \
        /usr/lib/systemd/system-sleep/school-forget-wifi \
        /usr/local/lib/school-account/create-student \
        /usr/local/lib/school-account/student-account-service.py \
        /usr/share/gnome-shell/extensions/school-account@school.local/extension.js
    do
        [ -e "$path" ] && cp -a --parents "$path" "$BACKUP/"
    done
    say "backed up the original files to $BACKUP"
fi

# --- Wi-Fi forgetting: logout only, plus the suspend fix ---------------------
# New forget script first: it honours the skip file, so restarting the watcher
# below (whose stop step runs the forget script) doesn't drop the current Wi-Fi.
install_file files/usr/local/sbin/school-forget-wifi        /usr/local/sbin/school-forget-wifi 755
install_file files/usr/local/sbin/school-forget-wifi-watch  /usr/local/sbin/school-forget-wifi-watch 755
install_file files/etc/systemd/system/school-forget-wifi.service /etc/systemd/system/school-forget-wifi.service 644
install_file files/usr/lib/systemd/system-sleep/school-forget-wifi /usr/lib/systemd/system-sleep/school-forget-wifi 755
touch /run/school-forget-wifi.skip
systemctl daemon-reload
systemctl restart school-forget-wifi.service
rm -f /run/school-forget-wifi.skip

# --- Account creation (login screen) -----------------------------------------
install_file files/usr/local/lib/school-account/tdsb_wifi.py   /usr/local/lib/school-account/tdsb_wifi.py 644
install_file files/usr/local/lib/school-account/create-student /usr/local/lib/school-account/create-student 755
install_file files/usr/local/lib/school-account/student-account-service.py /usr/local/lib/school-account/student-account-service.py 644
install_file files/usr/local/lib/school-account/tdsb-pam-auth  /usr/local/lib/school-account/tdsb-pam-auth 755
install_file files/usr/share/gnome-shell/extensions/school-account@school.local/extension.js \
             /usr/share/gnome-shell/extensions/school-account@school.local/extension.js 644
rm -rf /usr/local/lib/school-account/__pycache__
systemctl restart school-student-account.service

# --- Login rules (last, after everything they call is in place) --------------
[ -e /var/log/school-account-tdsb.log ] || install -o root -g root -m 600 /dev/null /var/log/school-account-tdsb.log
install_file files/etc/pam.d/gdm-password "$PAM_FILE" 644

say "done. The new login screen appears the next time a student logs out."
