#!/bin/bash
# 0034-snipping-tool-xournal-settings (teacher requests, 2026-10-21).
#  1. A Snipping Tool for everyone (menu entry "Snipping Tool", and the
#     Super+Shift+S shortcut like Windows): GNOME's area picker (drag a box),
#     then the picture opens in Swappy to mark up (pen, text, arrow, box,
#     circle, blur) and Copy. /usr/local/bin/lab-snip does this.
#     Flameshot and Ksnip were tried first: both fail on GNOME 50 ("Unable to
#     capture screen") because they ask GNOME for a silent screenshot, which it
#     refuses; this uses the interactive request, which GNOME allows.
#  2. Xournal++ settings of the teacher's computer, refreshed for every admin
#     account (sudo group): pen button 1 = hold to erase, button 2 = select
#     region (unchanged since 0018), plus the pen colour and starting tool as
#     they are now. A copy of the old file is kept as settings.xml.before-0034.
# Safe to re-run. If an admin has Xournal++ open, the Xournal++ part waits
# (exit 1, retried on the next run); the Snipping Tool part is already done.
source "$LAB_UPDATER_HELPERS"

# ---- Snipping Tool
apt_install swappy wl-clipboard libnotify-bin
install_file files/usr/local/bin/lab-snip                          /usr/local/bin/lab-snip 755
install_file files/usr/local/share/applications/lab-snip.desktop   /usr/local/share/applications/lab-snip.desktop 644

profile=/etc/dconf/profile/user
install -d -m 755 /etc/dconf/profile
if [ ! -f "$profile" ]; then
    printf 'user-db:user\nsystem-db:local\n' > "$profile"
    chmod 644 "$profile"
    say "created $profile"
elif ! grep -qx 'system-db:local' "$profile"; then
    echo 'system-db:local' >> "$profile"
    say "added system-db:local to $profile"
fi
install_file files/etc/dconf/db/local.d/50-lab-snip /etc/dconf/db/local.d/50-lab-snip 644
dconf update
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/local/share/applications || true
say "Snipping Tool ready (menu: Snipping Tool; Super+Shift+S after the next login)"

# ---- Xournal++ settings for admin accounts
snap_installed() { snap list xournalpp >/dev/null 2>&1; }
deb_installed()  { [ "$(dpkg-query -W -f='${Status}' xournalpp 2>/dev/null)" = "install ok installed" ]; }
if ! snap_installed && ! deb_installed; then
    say "Xournal++ is not installed on this laptop; skipping its settings"
    exit 0
fi

admins=()
for user in $(getent group sudo | cut -d: -f4 | tr ',' ' '); do
    IFS=: read -r _ _ uid _ _ home _ < <(getent passwd "$user") || continue
    if [ "$uid" -ge 1000 ] && [ -d "$home" ]; then
        admins+=("$user:$home")
    fi
done
[ "${#admins[@]}" -gt 0 ] || { say "no admin accounts found"; exit 0; }

for entry in "${admins[@]}"; do
    user="${entry%%:*}"
    if pgrep -u "$user" -x xournalpp >/dev/null; then
        say "Xournal++ is open in $user's session; its settings will be written on the next run"
        exit 1
    fi
done

as_user() { local user="$1"; shift; runuser -u "$user" -- "$@"; }
SETTINGS="$PWD/files/settings.xml"     # snap paths (/snap/xournalpp/current/...)

put_settings() {        # user, settings folder, path prefix of the app's data
    local user="$1" dir="$2" prefix="$3"
    as_user "$user" mkdir -p "$dir/palettes" "$dir/plugins"
    if [ -f "$dir/settings.xml" ] && [ ! -e "$dir/settings.xml.before-0034" ]; then
        as_user "$user" cp -p "$dir/settings.xml" "$dir/settings.xml.before-0034"
    fi
    sed "s#/snap/xournalpp/current/usr/#$prefix#g" "$SETTINGS" \
        | as_user "$user" tee "$dir/settings.xml.new" >/dev/null
    as_user "$user" mv -f "$dir/settings.xml.new" "$dir/settings.xml"
    say "settings written for $user: $dir/settings.xml"
}

for entry in "${admins[@]}"; do
    user="${entry%%:*}" home="${entry#*:}"
    if snap_installed; then
        snap_rev="$(snap list xournalpp | awk 'NR==2 {print $3}')"
        if [ ! -e "$home/snap/xournalpp/current" ]; then
            as_user "$user" mkdir -p "$home/snap/xournalpp/$snap_rev"
            as_user "$user" ln -sfn "$snap_rev" "$home/snap/xournalpp/current"
        fi
        put_settings "$user" "$home/snap/xournalpp/current/.config/xournalpp" /snap/xournalpp/current/usr/
    fi
    if deb_installed; then
        put_settings "$user" "$home/.config/xournalpp" /usr/
    fi
done
say "done"
