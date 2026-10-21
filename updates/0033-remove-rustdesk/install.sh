#!/bin/bash
# 0033-remove-rustdesk (teacher request, 2026-10-21).
# Remove RustDesk from every laptop: it is not needed on the lab laptops and
# does not work over TDSB Wi-Fi. Undoes only the RustDesk part of 0031-desktop-apps
# (0031 itself stays published and unchanged; Chrome, ChatGPT and Claude Desktop
# are NOT touched). Stops and disables the service, purges the package, removes
# the lab launcher/menu files and the admin menu entries 0031 created.
# Not touched: RustDesk settings in users' home folders (~/.config/rustdesk).
# Safe to rerun; does nothing if RustDesk is already gone.
source "$LAB_UPDATER_HELPERS"

systemctl disable --now rustdesk.service >/dev/null 2>&1 || true
pkill -x rustdesk >/dev/null 2>&1 || true

packages=()
for pkg in rustdesk-unattended-wayland rustdesk; do
    if [ "$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)" != '' ] \
       && [ "$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)" != 'unknown ok not-installed' ]; then
        packages+=("$pkg")
    fi
done
if [ "${#packages[@]}" -gt 0 ]; then
    apt-get -o DPkg::Lock::Timeout=900 purge -y "${packages[@]}"
    say "purged ${packages[*]}"
fi

rm -f /usr/local/bin/lab-rustdesk \
      /usr/local/share/applications/rustdesk.desktop \
      /usr/local/share/applications/rustdesk-link.desktop \
      /etc/xdg/autostart/lab-rustdesk-menu.desktop \
      /etc/systemd/system/rustdesk.service \
      /usr/lib/systemd/system/rustdesk.service \
      /usr/lib/systemd/user/rustdesk.service
rm -rf /usr/local/lib/lab-rustdesk

# Admin menu entries made by 0031 (only files carrying its marker).
while IFS=: read -r user _ uid _ _ home _; do
    [ "$uid" -ge 1000 ] && [ -d "$home" ] || continue
    entry="$home/.local/share/applications/rustdesk.desktop"
    if [ -f "$entry" ] && grep -q '^X-Lab-RustDesk-Menu=true$' "$entry"; then
        rm -f "$entry"
        say "removed RustDesk menu entry for $user"
    fi
done < <(getent passwd)

systemctl daemon-reload
say "RustDesk removed; Chrome, ChatGPT and Claude Desktop unchanged"
