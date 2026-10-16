#!/bin/bash
# Prepare an up-to-date lab laptop to be captured as a NEW Clonezilla master image.
#
# On the laptop, logged in as administrator (everyone else logged out):
#     git clone -q https://github.com/mendelellenbogen-afk/mr-ellenbogen-linux-lab-updates ~/lab-setup
#     sudo bash ~/lab-setup/bootstrap/prepare-image.sh --dry-run    # shows what would happen
#     sudo bash ~/lab-setup/bootstrap/prepare-image.sh              # does it (asks you to type IMAGE)
#
# It makes sure every lab update is installed, then:
#   * deletes every account except administrator, studenttest1, studenttest2
#     (student/staff TDSB accounts and anything else), with their files,
#   * forgets all Wi-Fi, clears logs, shell histories and pending requests,
#   * resets the laptop's name and machine ID so every clone gets its own,
#   * puts the laptop on the normal update channel (main).
# Then you shut down and save the image with Clonezilla.
set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
KEEP_ACCOUNTS="administrator studenttest1 studenttest2"
KEEP_ACCOUNTS+=" teststudent studenttwo"   # old names; renamed by update 0010 before anything is deleted
GENERIC_NAME="lab-new"
MAX_DISK_BYTES=260000000000      # 256 GB drives are ~256,060,514,304 bytes

say()  { echo ">>> $*"; }
warn() { echo "!!! $*"; }
do_it() {
    if [ "$DRY_RUN" = 1 ]; then echo "    would run: $*"; else "$@"; fi
}

if [ "$DRY_RUN" = 0 ] && [ "$EUID" -ne 0 ]; then
    echo "Run with sudo (or add --dry-run to only look)."; exit 1
fi

# --- 1. Is this laptop a good master? ------------------------------------------
root_part="$(findmnt -no SOURCE /)"
disk="$(lsblk -no PKNAME "$root_part" | head -n 1)"
disk_bytes="$(lsblk -bdno SIZE "/dev/$disk")"
say "Laptop serial: $(cat /sys/class/dmi/id/product_serial 2>/dev/null || echo unknown) ($(cat /sys/class/dmi/id/product_name 2>/dev/null))"
say "System drive: /dev/$disk, $((disk_bytes / 1000000000)) GB"
if [ "$disk_bytes" -gt "$MAX_DISK_BYTES" ]; then
    warn "This drive is LARGER than 256 GB. An image from it can't be restored onto"
    warn "256 GB laptops. Use a laptop with a 256 GB (or smaller) drive instead."
    [ "$DRY_RUN" = 1 ] || exit 1
fi

shopt -s nullglob
if [ -z "$(echo "$REPO"/updates/[0-9][0-9][0-9][0-9]-*/)" ]; then
    warn "Can't find the lab updates next to this script ($REPO/updates)."; exit 1
fi
missing_updates() {
    for folder in "$REPO"/updates/[0-9][0-9][0-9][0-9]-*/; do
        name="$(basename "$folder")"
        [ -e "/var/lib/lab-updater/applied/$name" ] || echo "$name"
    done
}
if [ ! -f /etc/lab-updater/config ]; then
    warn "The lab updater is not installed on this laptop. Run the class setup command first."
    exit 1
fi
missing="$(missing_updates)"
if [ -n "$missing" ]; then
    say "Updates not installed yet: $(echo $missing)"
    if [ "$DRY_RUN" = 0 ]; then
        say "Installing them now (needs Wi-Fi)..."
        systemctl start lab-updater.service || true
        missing="$(missing_updates)"
        if [ -n "$missing" ]; then
            warn "Still missing: $(echo $missing). Connect to Wi-Fi and try again."
            exit 1
        fi
    fi
fi
[ -n "$missing" ] || say "All lab updates are installed."

# Update 0010 renames/resets the test accounts; finish that before choosing what to delete.
if [ -x /usr/local/sbin/lab-reset-test-accounts ] && [ ! -e /var/lib/school-account/test-accounts-reset/complete ]; then
    if [ "$DRY_RUN" = 1 ]; then
        say "Test accounts not reset yet (update 0010); the real run does it first."
    else
        say "Finishing the test account reset (StudentTest1/StudentTest2)"
        /usr/local/sbin/lab-reset-test-accounts || { warn "A test account is still logged in. Log it out and run this again."; exit 1; }
    fi
fi

# --- 2. Which accounts go? -------------------------------------------------------
to_delete=()
while IFS=: read -r name _ uid _ _ home shell; do
    [ "$uid" -ge 1000 ] && [ "$uid" -lt 60000 ] || continue
    case " $KEEP_ACCOUNTS " in *" $name "*) continue ;; esac
    to_delete+=("$name")
done < /etc/passwd

say "Accounts kept:    $KEEP_ACCOUNTS"
say "Accounts deleted: ${to_delete[*]:-(none)}"

logged_in="$(loginctl list-sessions --no-legend | awk '$6 == "user" { print $3 }' | sort -u | grep -vx administrator || true)"
if [ -n "$logged_in" ]; then
    warn "Still logged in: $(echo $logged_in). Log them out (or restart) and run this again."
    exit 1
fi

if [ "$DRY_RUN" = 1 ]; then
    say "DRY RUN: nothing will be changed. Steps it would take:"
else
    echo
    echo "This permanently deletes the accounts above and their files, and resets this"
    echo "laptop for imaging. Type IMAGE to continue:"
    read -r answer
    [ "$answer" = "IMAGE" ] || { echo "Cancelled. Nothing was changed."; exit 1; }
fi

# --- 3. Clean up -----------------------------------------------------------------
say "Normal update channel (main)"
do_it sed -i 's/^BRANCH=.*/BRANCH=main/' /etc/lab-updater/config

for name in "${to_delete[@]}"; do
    say "Deleting account $name"
    do_it userdel --remove "$name"
done

say "Clearing pending requests, update logs and status"
do_it find /var/lib/school-account/self-delete-scheduled /run/school-account-self-delete /run/lab-messages -mindepth 1 -delete
do_it truncate -s 0 /var/lib/school-account/legacy-to-remove
do_it rm -f /var/lib/lab-updater/status.json
do_it rm -rf /var/lib/lab-inventory          # 0022: per-laptop key and login times; each clone makes its own
do_it find /var/log/lab-updater -type f -delete
do_it truncate -s 0 /var/log/school-account-tdsb.log

say "Clearing shell histories, old logs and package downloads"
do_it rm -f /root/.bash_history /home/administrator/.bash_history /home/studenttest1/.bash_history /home/studenttest2/.bash_history
do_it journalctl --rotate
do_it journalctl --vacuum-time=1s
do_it find /var/log -type f \( -name "*.gz" -o -name "*.[0-9]" -o -name "*.old" \) -delete
do_it apt-get clean
do_it find /tmp /var/tmp -mindepth 1 -maxdepth 1 ! -name "systemd-private-*" -exec rm -rf {} +

say "Unused SSH host keys (each clone would otherwise share them)"
do_it find /etc/ssh -name "ssh_host_*" -delete

say "Laptop name -> $GENERIC_NAME (each clone renames itself lab-<serial> at boot)"
do_it hostnamectl set-hostname "$GENERIC_NAME"
do_it sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$GENERIC_NAME/" /etc/hosts

say "Machine ID emptied (each clone creates its own at first boot)"
do_it truncate -s 0 /etc/machine-id
do_it rm -f /var/lib/systemd/random-seed

say "Forgetting all Wi-Fi (this disconnects the laptop)"
do_it /usr/local/sbin/school-forget-wifi --all     # incl. networks remembered for teacher/test accounts (0015)
do_it rm -f /var/lib/NetworkManager/*.lease

do_it rm -rf /home/administrator/lab-setup

echo
if [ "$DRY_RUN" = 1 ]; then
    say "DRY RUN finished. Run again without --dry-run to do it."
else
    say "DONE. Next: shut down (sudo systemctl poweroff -i), DON'T start Ubuntu again,"
    say "boot from the Clonezilla USB and save this disk as the new image."
fi
