#!/bin/bash
# 0029-taken-home (the user's request, 2026-10-19)
# Find the laptops students take home. The inventory report (0022) now also
# says who is logged in and whether the laptop is on the school Wi-Fi
# (TDSB-WIFI), on another Wi-Fi, or on none. On another Wi-Fi it asks a Wi-Fi
# location service (LOCATION_URL in /etc/lab-inventory/config) where it is,
# once per network visit. The name of a home network is never sent. A report
# goes out as soon as a Wi-Fi connection comes up (NetworkManager dispatcher),
# still signed and encrypted to the teacher's key. The teacher's computer
# turns the reports into the "Taken home" list.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-inventory/lab-inventory-report  /usr/local/lib/lab-inventory/lab-inventory-report 755
install_file files/etc/lab-inventory/config                         /etc/lab-inventory/config 644
install_file files/etc/NetworkManager/dispatcher.d/91-lab-inventory /etc/NetworkManager/dispatcher.d/91-lab-inventory 755

systemctl start --no-block lab-inventory.service
say "lab inventory: now also reports school/other Wi-Fi (and the location off-site) when Wi-Fi connects"
