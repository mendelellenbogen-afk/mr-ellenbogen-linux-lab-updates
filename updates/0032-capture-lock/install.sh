#!/bin/bash
# 0032-capture-lock, 2026-10-20: teacher requests built-in/USB camera and
# microphone denial for students, default off for admins with per-laptop override.
# Keep Bluetooth and speaker/headphone playback. Permission policy, not a physical
# hardware disconnect. Reboot needed to terminate pre-existing capture handles.
source "$LAB_UPDATER_HELPERS"

if ! command -v setfacl >/dev/null; then apt_install acl; fi
install -d -o root -g root -m 755 /etc/lab-capture
install_file files/etc/udev/rules.d/72-lab-capture.rules /etc/udev/rules.d/72-lab-capture.rules 644
install_file files/etc/udev/rules.d/99-lab-capture-acl.rules /etc/udev/rules.d/99-lab-capture-acl.rules 644
install_file files/usr/local/sbin/lab-capture-policy /usr/local/sbin/lab-capture-policy 755
# No markers created: locked by default. Reruns preserve the admin's overrides.
/usr/local/sbin/lab-capture-policy refresh
request_reboot
say "Capture locked by default; reboot needed. Bluetooth left unchanged."
