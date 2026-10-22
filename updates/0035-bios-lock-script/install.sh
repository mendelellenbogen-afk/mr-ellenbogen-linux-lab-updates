#!/bin/bash
# 0035-bios-lock-script (teacher request, 2026-10-21).
# Install the command lab-bios-lock on every laptop, so the teacher can set the
# BIOS admin password by hand from ANY session (a student's too), typing an
# administrator password when asked:
#     pkexec /usr/local/sbin/lab-bios-lock --status    (from a student or admin terminal)
#     sudo lab-bios-lock --status                         (from an admin account)
# Drop --status to set or change the password; --remove to take it off.
# The script asks for the BIOS password on the keyboard and stores it nowhere;
# this update sets no password and changes no BIOS setting. Students cannot run
# it as root (they are not in the sudo group), so it does nothing for them.
# One system copy, so accounts created later have it too. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/lab-bios-lock /usr/local/sbin/lab-bios-lock 755
say "lab-bios-lock installed; use: pkexec /usr/local/sbin/lab-bios-lock --status"
