#!/bin/bash
# 0009-name-on-boot
# Every boot, the laptop names itself "lab-" + serial (same rule as 0007).
# Needed for laptops cloned from a new image: they start with a generic name
# and an empty machine ID (which systemd fills in at first boot).
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/sbin/lab-set-hostname              /usr/local/sbin/lab-set-hostname 755
install_file files/etc/systemd/system/lab-set-hostname.service  /etc/systemd/system/lab-set-hostname.service 644
systemctl daemon-reload
systemctl enable lab-set-hostname.service
/usr/local/sbin/lab-set-hostname
say "this laptop is named $(hostname)"
