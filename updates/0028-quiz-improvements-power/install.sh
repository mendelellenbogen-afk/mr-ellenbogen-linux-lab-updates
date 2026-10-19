#!/bin/bash
# 0028-quiz-improvements-power (the teacher's feedback after the first live
# quiz, 2026-10-18)
# Quizzes (0027):
#  * First and last name in separate boxes, the student ID shown (not
#    editable), and "Edit name" to go back to that page.
#  * Hand in: the student types HAND IN, then a big 5-second countdown that
#    can still be cancelled.
#  * Questions with a Run button start with the whole program (class, main
#    method, the given values); "Reset code" puts it back.
#  * Hand-ins carry first and last name separately.
# Power (all laptops, all accounts, locked):
#  * Performance power mode, kept by lab-performance.timer (boot + every 5 min).
#  * Battery percentage always shown; the screen never blanks; never suspends
#    by itself on battery or plugged in (also on the login screen); no switch
#    to power-saver on low battery. Closing the lid still suspends.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

# ---- quizzes
install_file files/usr/local/lib/lab-quiz/lab-quiz-agent.py /usr/local/lib/lab-quiz/lab-quiz-agent.py 755
install_file files/usr/local/lib/lab-quiz/quiz-window.py    /usr/local/lib/lab-quiz/quiz-window.py 755
systemctl restart lab-quiz.service

# ---- power: GNOME settings for every account, locked
profile=/etc/dconf/profile/user
install -d -m 755 /etc/dconf/profile
if [ ! -f "$profile" ]; then
    printf 'user-db:user\nsystem-db:local\n' > "$profile"
    chmod 644 "$profile"
    say "created $profile"
elif ! grep -qx 'system-db:local' "$profile"; then
    echo 'system-db:local' >> "$profile"
    say "added system-db:local to $profile"
fi
install_file files/etc/dconf/db/local.d/50-lab-power       /etc/dconf/db/local.d/50-lab-power 644
install_file files/etc/dconf/db/local.d/locks/50-lab-power /etc/dconf/db/local.d/locks/50-lab-power 644
dconf update
say "power settings compiled (open sessions pick them up right away)"

# ---- power: the login screen
install_file files/usr/share/gdm/dconf/98-lab-power              /usr/share/gdm/dconf/98-lab-power 644
install_file files/usr/share/gdm/dconf/locks/98-lab-power-locks /usr/share/gdm/dconf/locks/98-lab-power-locks 644
if [ -x /usr/share/gdm/generate-config ] && /usr/share/gdm/generate-config; then
    say "login screen settings recompiled"
else
    say "could not recompile the login screen settings now; GDM does it at the next restart"
fi

# ---- power: Performance mode
install_file files/usr/local/sbin/lab-performance                 /usr/local/sbin/lab-performance 755
install_file files/etc/systemd/system/lab-performance.service    /etc/systemd/system/lab-performance.service 644
install_file files/etc/systemd/system/lab-performance.timer      /etc/systemd/system/lab-performance.timer 644
systemctl daemon-reload
systemctl enable --now lab-performance.timer
systemctl start lab-performance.service || say "couldn't set Performance mode now; the timer tries again"
say "done"
