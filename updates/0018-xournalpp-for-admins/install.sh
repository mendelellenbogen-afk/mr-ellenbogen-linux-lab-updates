#!/bin/bash
# 0018-xournalpp-for-admins (the user's choices, 2026-10-15)
#  * Installs Xournal++ (snap, the same version as on the teacher's computer),
#    unless some Xournal++ (snap or apt) is already installed.
#  * Every admin account (sudo group; only administrator today) gets the
#    teacher's exact Xournal++ settings: pen buttons (1 = hold to erase strokes,
#    2 = select region), eraser end, mouse left/middle/right buttons, the Wacom
#    Intuos S pen registered as a pen, tools, colours, toolbar, autosave...
#    Existing settings are replaced (a copy is kept as settings.xml.before-0018).
#  * Only admins see it in the app menu. (Students could still start it from
#    a terminal; this hides it, it doesn't lock it.)
#  * Pen buttons and tablet area are left at GNOME's defaults (buttons go
#    straight to Xournal++, the tablet covers the whole screen).
# Safe to re-run. Fails (and retries later) if an admin has Xournal++ open,
# because Xournal++ rewrites its settings file when it closes.
source "$LAB_UPDATER_HELPERS"

SETTINGS="$PWD/files/settings.xml"     # snap paths (/snap/xournalpp/current/...)

snap_installed() { snap list xournalpp >/dev/null 2>&1; }
deb_installed()  { [ "$(dpkg-query -W -f='${Status}' xournalpp 2>/dev/null)" = "install ok installed" ]; }

if snap_installed || deb_installed; then
    say "Xournal++ already installed; fixing its settings"
else
    snap install xournalpp
    say "installed Xournal++ $(snap list xournalpp | awk 'NR==2 {print $2}') (snap)"
fi

# Admin accounts: sudo group members with a normal home folder.
admins=()
for user in $(getent group sudo | cut -d: -f4 | tr ',' ' '); do
    IFS=: read -r _ _ uid _ _ home _ < <(getent passwd "$user") || continue
    if [ "$uid" -ge 1000 ] && [ -d "$home" ]; then
        admins+=("$user:$home")
    fi
done
[ "${#admins[@]}" -gt 0 ] || say "no admin accounts found"

for entry in "${admins[@]}"; do
    user="${entry%%:*}"
    if pgrep -u "$user" -x xournalpp >/dev/null; then
        say "Xournal++ is open in $user's session; will retry on the next run"
        exit 1
    fi
done

# Write files as the admin (never as root inside a user's home folder).
as_user() { local user="$1"; shift; runuser -u "$user" -- "$@"; }

put_settings() {        # user, settings folder, path prefix of the app's data
    local user="$1" dir="$2" prefix="$3"
    as_user "$user" mkdir -p "$dir/palettes" "$dir/plugins"
    if [ -f "$dir/settings.xml" ] && [ ! -e "$dir/settings.xml.before-0018" ]; then
        as_user "$user" cp -p "$dir/settings.xml" "$dir/settings.xml.before-0018"
    fi
    sed "s#/snap/xournalpp/current/usr/#$prefix#g" "$SETTINGS" \
        | as_user "$user" tee "$dir/settings.xml.new" >/dev/null
    as_user "$user" mv -f "$dir/settings.xml.new" "$dir/settings.xml"
    say "settings written for $user: $dir/settings.xml"
}

# Menu: a hidden copy in /usr/local/share/applications wins over the app's own
# entry for everyone; each admin's own copy in ~/.local wins over that.
menu_entries=()
if snap_installed; then
    snap_rev="$(snap list xournalpp | awk 'NR==2 {print $3}')"
    for entry in "${admins[@]}"; do
        user="${entry%%:*}" home="${entry#*:}"
        # The snap keeps its settings in ~/snap/xournalpp/current/. Before its
        # first start that folder doesn't exist yet; create it the way snapd does.
        if [ ! -e "$home/snap/xournalpp/current" ]; then
            as_user "$user" mkdir -p "$home/snap/xournalpp/$snap_rev"
            as_user "$user" ln -sfn "$snap_rev" "$home/snap/xournalpp/current"
        fi
        put_settings "$user" "$home/snap/xournalpp/current/.config/xournalpp" /snap/xournalpp/current/usr/
    done
    menu_entries+=(/var/lib/snapd/desktop/applications/xournalpp_xournalpp.desktop)
fi
if deb_installed; then
    for entry in "${admins[@]}"; do
        user="${entry%%:*}" home="${entry#*:}"
        put_settings "$user" "$home/.config/xournalpp" /usr/
    done
    menu_entries+=(/usr/share/applications/com.github.xournalpp.xournalpp.desktop)
fi

for source in "${menu_entries[@]}"; do
    if [ ! -f "$source" ]; then
        say "menu entry $source missing"
        exit 1
    fi
    id="$(basename "$source")"
    grep -v '^NoDisplay=' "$source" | sed '/^\[Desktop Entry\]$/a NoDisplay=true' > "$id.hidden"
    install_file "$id.hidden" "/usr/local/share/applications/$id" 644
    rm -f "$id.hidden"
    for entry in "${admins[@]}"; do
        user="${entry%%:*}" home="${entry#*:}"
        as_user "$user" mkdir -p "$home/.local/share/applications"
        grep -v '^NoDisplay=' "$source" | as_user "$user" tee "$home/.local/share/applications/$id" >/dev/null
        say "menu entry shown for $user"
    done
done
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/local/share/applications || true
say "done"
