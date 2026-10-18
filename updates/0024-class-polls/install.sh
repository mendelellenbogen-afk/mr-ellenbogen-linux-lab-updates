#!/bin/bash
# 0024-class-polls (the user's request, 2026-10-18)
# The teacher can push a multiple-choice poll to every logged-in laptop and
# show the live results to the class (tools/lab-poll + a results page on the
# teacher's computer).
# * The live-messages listener also listens on POLL_TOPIC. A lab-signed
#   "poll" opens poll-window.py in each desktop session; "poll_close" turns
#   every window into the results (bars, percentages, no names).
# * The teacher's choices: students can change their answer until the poll
#   closes; the window can't be closed before answering; results are shown
#   to the students when the poll closes.
# * Answers: the window drops the choice in /run/lab-messages/poll-answers
#   (sticky, like /tmp); the listener takes the account from the file's
#   owner, signs it with this laptop's inventory key (update 0022) and
#   encrypts it to the teacher's key before posting it on POLL_ANSWER_TOPIC.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755
install_file files/usr/local/lib/lab-messages/poll-window.py           /usr/local/lib/lab-messages/poll-window.py 755
install_file files/etc/lab-messages/config                             /etc/lab-messages/config 644

# The answers are signed with the laptop key that the inventory makes.
[ -f /var/lib/lab-inventory/laptop-key ] || systemctl start lab-inventory.service \
    || say "no laptop key yet: poll answers start working after the next inventory report"

systemctl restart lab-messages.service
say "class polls ready (laptop $(hostname))"
