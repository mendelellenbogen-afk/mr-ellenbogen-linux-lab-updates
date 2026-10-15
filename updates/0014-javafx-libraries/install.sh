#!/bin/bash
# 0014-javafx-libraries
# Wizard JavaFX projects with extra libraries ticked (ControlsFX, FormsFX,
# ValidatorFX, Ikonli, BootstrapFX, TilesFX, FXGL) compiled but failed at Run:
# "Module ... not found, required by ...". IntelliJ puts those libraries' own
# dependencies on the classpath, which a modular app can't see. The JavaFX
# helper (from 0013) now also moves module-info.java out of such projects
# (backup kept), so they run from the classpath via Launcher. Tested on the
# test laptop by hand first (2026-10-14). Projects with only JavaFX keep
# module-info.java. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-javafx/javafx-pom-fixer.py /usr/local/lib/lab-javafx/javafx-pom-fixer.py 755

# Restart the helper for everyone logged in, so the new version runs now.
for user in $(loginctl list-sessions --no-legend | awk '$6 == "user" { print $3 }' | sort -u); do
    if [ "$(id -u "$user")" -ge 1000 ]; then
        if systemctl --user -M "$user@" restart lab-javafx-pom-fixer.service 2> /dev/null; then
            say "restarted the JavaFX helper for $user"
        fi
    fi
done
say "done"
