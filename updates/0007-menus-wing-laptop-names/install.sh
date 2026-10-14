#!/bin/bash
# 0007-menus-wing-laptop-names
#  * PyCharm: add a menu icon for everyone (/opt/pycharm was installed but had none).
#  * Thonny: it lived in the administrator's private home folder, which students
#    can't open. Copy it to /opt/thonny for everyone and add a menu icon.
#    (The administrator's copy is left as it is.)
#  * Remove Wing Personal 7 (snap). Wing Personal 11 stays.
#  * Give each laptop its own name: "lab-" + hardware serial (e.g. lab-5cd1383hmm)
#    instead of "administrator" everywhere.
#  * Give each laptop its own machine ID if it still has the one copied from the
#    master image (completes at the next restart).
source "$LAB_UPDATER_HELPERS"

# --- PyCharm -------------------------------------------------------------------
if [ -x /opt/pycharm/bin/pycharm ]; then
    install_file files/usr/share/applications/pycharm.desktop /usr/share/applications/pycharm.desktop 644
else
    say "PyCharm not found in /opt/pycharm; skipping its menu icon"
fi

# --- Thonny --------------------------------------------------------------------
OLD=/home/administrator/apps/thonny
NEW=/opt/thonny
if [ ! -x "$NEW/bin/python" ] && [ -d "$OLD" ]; then
    rm -rf "$NEW.tmp"
    cp -a "$OLD" "$NEW.tmp"
    # A Python venv stores its own location in its scripts; point them at /opt.
    grep -rlI --null "$OLD" "$NEW.tmp/bin" "$NEW.tmp/pyvenv.cfg" | xargs -0 -r sed -i "s#$OLD#$NEW#g"
    find "$NEW.tmp" -name __pycache__ -type d -prune -exec rm -rf {} +
    chown -R root:root "$NEW.tmp"
    chmod -R u+rwX,go+rX,go-w "$NEW.tmp"
    mv "$NEW.tmp" "$NEW"
    say "copied Thonny to $NEW"
fi
if "$NEW/bin/python" -c "import thonny" 2>/dev/null; then
    install_file files/usr/share/applications/Thonny.desktop /usr/share/applications/Thonny.desktop 644
else
    say "Thonny not usable at $NEW; skipping its menu icon"
fi
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true

# --- Wing Personal 7 -----------------------------------------------------------
if snap list wing-personal7 >/dev/null 2>&1; then
    snap remove --purge wing-personal7
    say "removed Wing Personal 7"
fi

# --- Machine ID ------------------------------------------------------------------
IMAGE_MACHINE_ID=d2d96c23afb24f5cb920b01f41d394aa
if [ "$(cat /etc/machine-id 2>/dev/null)" = "$IMAGE_MACHINE_ID" ]; then
    rm -f /etc/machine-id
    systemd-machine-id-setup
    say "new machine ID $(cat /etc/machine-id) (fully used after the next restart)"
    request_reboot
fi

# --- Laptop name -----------------------------------------------------------------
serial="$(tr 'A-Z' 'a-z' < /sys/class/dmi/id/product_serial 2>/dev/null | tr -cd 'a-z0-9')"
case "$serial" in
    ""|none|default*|tobefilled*|notspecified*|systemserial*|0|00000000) serial="" ;;
esac
if [ -z "$serial" ]; then
    serial="$(head -c 8 /etc/machine-id)"        # no usable serial: use the (now unique) machine ID
fi
name="lab-${serial:0:59}"
if [ "$(hostname)" != "$name" ]; then
    old_name="$(hostname)"
    hostnamectl set-hostname "$name"
    if grep -q '^127\.0\.1\.1' /etc/hosts; then
        sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$name/" /etc/hosts
    else
        printf '127.0.1.1\t%s\n' "$name" >> /etc/hosts
    fi
    say "laptop renamed from '$old_name' to '$name'"
fi
