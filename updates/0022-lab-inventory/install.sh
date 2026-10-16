#!/bin/bash
# 0022-lab-inventory (the user's request, 2026-10-16)
# Every 5 minutes, while someone is logged in (the only time laptops are
# online), the laptop sends the teacher a report if anything changed (or once
# a day): name, serial, model, BIOS, CPU, RAM, disks, battery, Wi-Fi, OS, lab
# update, and its accounts - tdsb-<ID> students with their last login time.
# The report is signed with this laptop's own key and encrypted to the
# teacher's public key; the ntfy topic is public, but only the teacher's
# computer can read it. Login times come from systemd's session start time.
# State: /var/lib/lab-inventory (root only; prepare-image.sh deletes it).
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-inventory/lab-inventory-report /usr/local/lib/lab-inventory/lab-inventory-report 755
install_file files/etc/lab-inventory/config                        /etc/lab-inventory/config 644
install_file files/etc/lab-inventory/teacher-key.pub.pem           /etc/lab-inventory/teacher-key.pub.pem 644
install_file files/etc/systemd/system/lab-inventory.service        /etc/systemd/system/lab-inventory.service 644
install_file files/etc/systemd/system/lab-inventory.timer          /etc/systemd/system/lab-inventory.timer 644

install -d -m 700 /var/lib/lab-inventory
systemctl daemon-reload
systemctl enable --now lab-inventory.timer
systemctl start --no-block lab-inventory.service
say "lab inventory: reporting every 5 minutes while someone is logged in"
