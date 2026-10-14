#!/bin/bash
# Run by ../setup as root (through pkexec) after the lab signature was checked.
#   1. Install the lab updater (same as the USB installer) and run all updates,
#      including 0004, which deletes every old-style account (the student
#      running this is deleted right after logout).
#   2. ONLY if every update succeeded: log the student out.
# If anything fails, nobody is logged out, and the teacher sees why.
set -euo pipefail

BRANCH="${1:-main}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATUS=/var/lib/lab-updater/status.json
REMOVE_LIST=/var/lib/school-account/legacy-to-remove

caller=""
if [ -n "${PKEXEC_UID:-}" ]; then
    caller="$(id -nu "$PKEXEC_UID" 2>/dev/null || true)"
fi

flag=""
[ "$BRANCH" = "testing" ] && flag="--testing"

bash "$HERE/lab-updater/usb-installer/install.sh" $flag

if ! python3 - "$STATUS" <<'PY'
import json, sys
status = json.load(open(sys.argv[1]))
ok = status.get("result") == "ok" and "0004-remove-old-accounts" in status.get("applied", [])
print(f">>> Updates: {status.get('result')} - {status.get('message')}")
sys.exit(0 if ok else 1)
PY
then
    echo
    echo "  SETUP DID NOT FINISH. Nobody was logged out."
    echo "  Teacher: check the Wi-Fi and run the command again, or see"
    echo "  journalctl -u lab-updater and /var/log/lab-updater/"
    exit 1
fi

echo
if [ -n "$caller" ] && grep -q "^$caller:" "$REMOVE_LIST" 2>/dev/null; then
    echo "  DONE! This old account ($caller) will now be deleted."
    echo "  You will be logged out in 15 seconds."
    echo "  Then create your new account at the login screen with your TDSB ID and password."
    echo
    sleep 15
    loginctl terminate-user "$caller"
else
    echo "  DONE! This laptop is set up. (The account '${caller:-unknown}' is kept.)"
fi
