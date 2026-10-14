#!/bin/bash
# 0008-live-messages
# Real-time pop-ups from the teacher (e.g. code snippets with a Copy button).
# A small service listens on the lab's ntfy.sh topic and shows messages signed
# with the lab key on every desktop logged in at that moment. Messages are never
# queued: a laptop that isn't logged in when one is sent never shows it.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755
install_file files/usr/local/lib/lab-messages/message-window.py        /usr/local/lib/lab-messages/message-window.py 755
install_file files/etc/lab-messages/config                             /etc/lab-messages/config 644
install_file files/etc/systemd/system/lab-messages.service             /etc/systemd/system/lab-messages.service 644

systemctl daemon-reload
systemctl enable lab-messages.service
systemctl restart lab-messages.service
