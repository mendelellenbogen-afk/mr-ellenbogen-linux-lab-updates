#!/bin/bash
# 0055-memory-guard
# Teacher's request 2026-11-02: laptops (all 8 GB) freeze when a program uses
# too much RAM (many Chrome tabs, IntelliJ, but any program can). Instead:
#  * zram: a compressed swap in RAM (lab-zram.service), used before the slow
#    disk swap file, so about 3x more fits before anything slows down;
#  * each program started from the desktop may use at most 60% of the RAM and
#    all of them together 80%; above that the kernel slows that program down
#    instead of the whole laptop (user drop-ins for app-*.scope, Firefox's snap
#    scope, app.slice; from each account's next login, and in open sessions
#    for programs started after this update);
#  * if a session still stalls on memory for 10 s (Ubuntu: 20 s), systemd-oomd
#    closes the program causing it;
#  * lab-memory-notice (a user service) tells the student which program was
#    closed and why.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

LIB=/usr/local/lib/lab-memory

install_file files$LIB/lab-zram           $LIB/lab-zram 755
install_file files$LIB/lab-memory-notice  $LIB/lab-memory-notice 755
install_file files/etc/sysctl.d/90-lab-memory.conf /etc/sysctl.d/90-lab-memory.conf 644
install_file files/etc/systemd/system/lab-zram.service /etc/systemd/system/lab-zram.service 644
install_file files/etc/systemd/system/user@.service.d/50-lab-memory.conf /etc/systemd/system/user@.service.d/50-lab-memory.conf 644
for dir in app-.scope.d snap.firefox.firefox-.scope.d app.slice.d; do
    install_file "files/etc/systemd/user/$dir/50-lab-memory.conf" "/etc/systemd/user/$dir/50-lab-memory.conf" 644
done
install_file files/etc/systemd/user/lab-memory-notice.service /etc/systemd/user/lab-memory-notice.service 644

sysctl --quiet --load=/etc/sysctl.d/90-lab-memory.conf || say "could not apply the memory settings now (they apply at the next start)"
systemctl daemon-reload
systemctl enable lab-zram.service
systemctl start lab-zram.service || say "could not start the zram swap now (it starts at the next boot)"
systemctl --global enable lab-memory-notice.service

# Open sessions: load the new limits and start the notice now.
for user in $(loginctl list-sessions --no-legend | awk '$6 == "user" { print $3 }' | sort -u); do
    if [ "$(id -u "$user")" -ge 1000 ]; then
        systemctl --user -M "$user@" daemon-reload 2> /dev/null || true
        systemctl --user -M "$user@" start lab-memory-notice.service 2> /dev/null ||
            say "could not start the memory notice for $user (it starts at the next login)"
    fi
done
say "done"
