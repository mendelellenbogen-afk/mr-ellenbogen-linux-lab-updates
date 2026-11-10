#!/bin/bash
# 0058-snipping-tool-v2 (teacher request, 2026-11-09: the snipping tool should
# work like the one on the teacher's own computer, from their spec).
#  - Super+Shift+S (shortcut from 0034, unchanged), the Snipping Tool menu entry,
#    or the editor's "+": every screen freezes and dims. Drag a box, or hover a
#    window (it lights up) and click to take the whole window. Esc cancels.
#    LEFT button = open the editor; RIGHT button = copy to the clipboard only.
#    Done by a new GNOME Shell add-on, lab-snip@school.local (inside GNOME, so no
#    permission prompt; correct on HiDPI and with two screens).
#  - The editor is Swappy 1.5.1 with the lab patch (swappy/ has the patch and
#    build.sh): the picture is already copied when it opens, right-click on the
#    picture copies it with the drawings, and a "+" button closes the editor and
#    starts a new snip. Save writes ~/Pictures/Screenshots/swappy-<date>.png.
#    Installed as /usr/local/lib/lab-snip/swappy; Ubuntu's /usr/bin/swappy stays.
#  - /usr/local/bin/lab-snip starts the add-on; if it isn't running yet (before
#    the next login) GNOME's area picker is used, as in 0034.
# The add-on starts at the next login. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

apt_install swappy wl-clipboard libnotify-bin     # libraries for the patched editor; fallback editor

install_file files/usr/local/lib/lab-snip/swappy  /usr/local/lib/lab-snip/swappy 755
install_file files/usr/local/bin/lab-snip         /usr/local/bin/lab-snip 755

ext=/usr/share/gnome-shell/extensions/lab-snip@school.local
for f in metadata.json extension.js geometry.js; do
    install_file "files$ext/$f" "$ext/$f" 644
done

# Switch the add-on on for every account (dconf default, as for 0034's shortcut).
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
install_file files/etc/dconf/db/local.d/50-lab-snip-extension /etc/dconf/db/local.d/50-lab-snip-extension 644
dconf update
say "Snipping Tool v2 ready (new snip screen after the next login; until then GNOME's picker)"
