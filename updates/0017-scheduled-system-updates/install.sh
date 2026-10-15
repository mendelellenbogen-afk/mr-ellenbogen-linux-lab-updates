#!/bin/bash
# 0017-scheduled-system-updates (the user's choices, 2026-10-15)
#  * ALL pending Ubuntu updates install automatically every 14 days, the next
#    time the laptop is online (lab-system-upgrade.timer; security updates
#    still install daily as before). Shutdown/suspend/lid are blocked while
#    packages install. Each laptop's first run is spread randomly over the
#    next 14 days so the lab doesn't download all at once.
#  * Students no longer see Ubuntu's "Software Updater" / "Firmware update
#    available" pop-ups (update-notifier now starts only for sudo-group users).
#  * Firmware is teacher-run only:  sudo lab-update-firmware  (needs AC power).
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/sbin/lab-system-upgrade                /usr/local/sbin/lab-system-upgrade 755
install_file files/usr/local/sbin/lab-update-firmware               /usr/local/sbin/lab-update-firmware 755
install_file files/usr/local/libexec/lab-update-notifier            /usr/local/libexec/lab-update-notifier 755
install_file files/etc/systemd/system/lab-system-upgrade.service    /etc/systemd/system/lab-system-upgrade.service 644
install_file files/etc/systemd/system/lab-system-upgrade.timer      /etc/systemd/system/lab-system-upgrade.timer 644

# First run: pretend the last full upgrade was 0-13 days ago, so laptops are
# spread over two weeks instead of all upgrading the day this update lands.
STAMP=/var/lib/lab-updater/system-upgrade.last
if [ ! -e "$STAMP" ]; then
    touch -d "$(( RANDOM % 14 )) days ago" "$STAMP"
    say "first full Ubuntu update due about $(date -d "@$(( $(stat -c %Y "$STAMP") + 14 * 86400 ))" +%F)"
fi

systemctl daemon-reload
systemctl enable --now lab-system-upgrade.timer

# Update prompts only for admins. Divert Ubuntu's autostart entry so package
# upgrades can't put the original back, and start our wrapper instead.
AUTOSTART=/etc/xdg/autostart/update-notifier.desktop
if ! dpkg-divert --list "$AUTOSTART" | grep -q .; then
    dpkg-divert --quiet --local --rename --divert "$AUTOSTART.distrib" --add "$AUTOSTART"
fi
if [ -f "$AUTOSTART.distrib" ]; then
    sed 's|^Exec=update-notifier.*|Exec=/usr/local/libexec/lab-update-notifier|' "$AUTOSTART.distrib" > "$AUTOSTART.tmp"
    grep -q '^Exec=/usr/local/libexec/lab-update-notifier' "$AUTOSTART.tmp" || { say "unexpected update-notifier.desktop"; exit 1; }
    install -m 644 "$AUTOSTART.tmp" "$AUTOSTART" && rm -f "$AUTOSTART.tmp"
    say "update prompts now only for admins (from next login)"
fi
say "done"
