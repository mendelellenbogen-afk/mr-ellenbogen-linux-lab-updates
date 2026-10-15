#!/bin/bash
# Read-only check: why is the TDSB "Create Account" panel missing from the
# login screen, or live messages not arriving? Changes nothing.   sudo bash check-login-panel.sh
EXT=/usr/share/gnome-shell/extensions/school-account@school.local
echo "== GNOME Shell: $(gnome-shell --version 2>/dev/null)"
echo "== extension.js sha (expect da378f0e3fad): $(sha256sum $EXT/extension.js 2>/dev/null | cut -c1-12)"
echo "== metadata shell-version: $(grep -o '"shell-version"[^]]*]' $EXT/metadata.json 2>/dev/null)"
echo "== GDM enable file: $(cat /usr/share/gdm/dconf/99-school-account 2>/dev/null | tr '\n' ' ')"
echo "== compiled GDM settings mention it: $(strings /usr/share/gdm/greeter-dconf-defaults 2>/dev/null | grep -c school-account)"
echo "== updates applied: $(ls /var/lib/lab-updater/applied/ | tail -n 3 | tr '\n' ' ')"
echo "== recent gdm/gnome-shell package changes:"
grep -hE " (upgrade|install) (gdm3|gnome-shell|gnome-shell-common):" /var/log/dpkg.log* 2>/dev/null | sort | tail -n 4
echo "== login-screen errors this boot:"
journalctl -b --no-pager 2>/dev/null | grep -iE "school-account|JS ERROR|Extension .* had error|extension.*(error|disabled)" | tail -n 8
echo "== clock: $(date '+%F %T %Z') | $(timedatectl show -p NTPSynchronized --value 2>/dev/null | sed 's/^/ntp-synced=/')"
echo "== live messages service: $(systemctl is-active lab-messages.service 2>/dev/null) / enabled: $(systemctl is-enabled lab-messages.service 2>/dev/null)"
journalctl -u lab-messages.service -b --no-pager -o cat 2>/dev/null | tail -n 5
echo "== Wi-Fi: $(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep -c wireless) active Wi-Fi connection(s)"
echo "DONE"
