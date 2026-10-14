#!/bin/bash
# Helpers for update install.sh scripts. Use them with:
#     source "$LAB_UPDATER_HELPERS"
#
# Every install.sh runs as root, non-interactively, from inside its own update
# folder, and must be safe to run again if it failed partway through.

set -euo pipefail

say() {
    echo "[$LAB_UPDATE_NAME] $*"
}

# Install apt packages, waiting for any other apt/dpkg run (e.g. unattended-upgrades).
apt_install() {
    apt-get -o DPkg::Lock::Timeout=900 update
    apt-get -o DPkg::Lock::Timeout=900 install -y --no-install-recommends "$@"
}

apt_remove() {
    apt-get -o DPkg::Lock::Timeout=900 remove -y "$@"
}

# Copy a file from this update folder into place with an owner and mode, e.g.
#     install_file files/school-forget-wifi /usr/local/sbin/school-forget-wifi 755
install_file() {
    local source="$1" target="$2" mode="${3:-644}"
    install -D -o root -g root -m "$mode" "$source" "$target"
    say "installed $target"
}

# Ask for a restart. Ubuntu shows its normal "restart required" notice.
request_reboot() {
    touch /run/reboot-required
    say "a restart is needed to finish this update"
}
