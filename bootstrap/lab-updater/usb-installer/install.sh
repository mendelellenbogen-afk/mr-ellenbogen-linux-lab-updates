#!/usr/bin/env bash
# One-time installer for the lab updater. Run it on each laptop from the USB:
#
#     sudo bash /run/media/administrator/ESD-USB/lab-updater/usb-installer/install.sh            # normal lab laptop
#     sudo bash /run/media/administrator/ESD-USB/lab-updater/usb-installer/install.sh --testing  # the test laptop
#
# It needs no internet. Running it again is safe (e.g. to switch channel).
# Student accounts and files are not touched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATER_DIR="$(dirname "$HERE")"
CLIENT="$UPDATER_DIR/client"
SETTINGS="$UPDATER_DIR/settings.conf"
SIGNERS="$UPDATER_DIR/keys/allowed_signers"

BRANCH=main
case "${1:-}" in
    "") ;;
    --testing) BRANCH=testing ;;
    *) echo "Usage: sudo bash install.sh [--testing]"; exit 2 ;;
esac

fail() { echo "ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Run this with sudo."
for tool in git python3 ssh-keygen systemctl; do
    command -v "$tool" >/dev/null || fail "Required program '$tool' is not installed."
done

[[ -f "$SETTINGS" ]] || fail "Missing $SETTINGS"
REPO_URL="$(sed -n 's/^REPO_URL=//p' "$SETTINGS" | tail -n 1)"
[[ "$REPO_URL" == https://github.com/* ]] || fail "REPO_URL in settings.conf is not set to a GitHub https URL."
[[ "$REPO_URL" != *OWNER/REPO* ]] || fail "REPO_URL in settings.conf still has the placeholder value."
[[ -s "$SIGNERS" ]] || fail "Missing or empty $SIGNERS (the trusted signing key)."

echo ">>> Installing lab updater files"
install -D -o root -g root -m 755 "$CLIENT/usr/local/lib/lab-updater/lab-updater.py"       /usr/local/lib/lab-updater/lab-updater.py
install -D -o root -g root -m 755 "$CLIENT/usr/local/lib/lab-updater/check-for-updates.py" /usr/local/lib/lab-updater/check-for-updates.py
install -D -o root -g root -m 644 "$CLIENT/usr/local/lib/lab-updater/update-helpers.sh"    /usr/local/lib/lab-updater/update-helpers.sh
install -D -o root -g root -m 644 "$CLIENT/etc/systemd/system/lab-updater.service"          /etc/systemd/system/lab-updater.service
install -D -o root -g root -m 644 "$CLIENT/etc/systemd/system/lab-updater.timer"            /etc/systemd/system/lab-updater.timer
install -D -o root -g root -m 755 "$CLIENT/etc/NetworkManager/dispatcher.d/90-lab-updater"  /etc/NetworkManager/dispatcher.d/90-lab-updater
install -D -o root -g root -m 644 "$CLIENT/etc/polkit-1/rules.d/45-lab-updater.rules"       /etc/polkit-1/rules.d/45-lab-updater.rules
install -D -o root -g root -m 644 "$CLIENT/usr/share/applications/lab-check-for-updates.desktop" /usr/share/applications/lab-check-for-updates.desktop

echo ">>> Writing settings (channel: $BRANCH)"
install -d -o root -g root -m 755 /etc/lab-updater
install -o root -g root -m 644 "$SIGNERS" /etc/lab-updater/allowed_signers
cat > /etc/lab-updater/config <<EOF
# Written by the lab updater USB installer on $(date -Iseconds)
REPO_URL=$REPO_URL
BRANCH=$BRANCH
EOF
chmod 644 /etc/lab-updater/config
install -d -o root -g root -m 755 /var/lib/lab-updater /var/log/lab-updater

echo ">>> Enabling automatic checks"
systemctl daemon-reload
systemctl enable --now lab-updater.timer
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true

echo ">>> Checking for updates now (fine if this laptop is offline)"
systemctl start lab-updater.service || true
if [[ -f /var/lib/lab-updater/status.json ]]; then
    python3 -c 'import json; s=json.load(open("/var/lib/lab-updater/status.json")); print("Result:", s.get("result"), "-", s.get("message"))'
fi

echo ">>> Done. Channel: $BRANCH. Serial: $(cat /sys/class/dmi/id/product_serial 2>/dev/null || echo unknown)"
