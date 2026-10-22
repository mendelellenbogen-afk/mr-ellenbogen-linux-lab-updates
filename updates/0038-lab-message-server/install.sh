#!/bin/bash
# 0038-lab-message-server (the teacher's request, 2026-10-22: "build a full
# solution use tailscale")
# Why: on 2026-10-22 several laptops never got the practice quiz. ntfy.sh lets
# only ~30 connections in from one address, every lab laptop shares the
# school's address, and each logged-in laptop holds 2, so only ~15 laptops
# got quizzes, messages, sounds and polls at once.
# Now the lab has its own message server: ntfy on the teacher's home computer,
# reached through Tailscale Funnel (an https://*.ts.net address; nothing to
# install on the laptops, no keys). The laptops use it first and fall back to
# ntfy.sh when it can't be reached, checking every 5 minutes for it to come
# back. The teacher's tools send on both servers and read both, and a message
# that arrives from both is shown once.
#  * lab-messages listener (live messages, sounds, polls), lab-quiz agent
#    (quizzes; the quiz firewall now allows both servers; the quiz file can
#    come from either), lab-inventory report.
#  * The three configs get PRIMARY_SERVER (everything else unchanged).
# Messages, polls and quizzes that are open right now carry on (the services
# restart; quiz answers are saved on disk). Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/etc/lab-messages/config  /etc/lab-messages/config 644
install_file files/etc/lab-quiz/config      /etc/lab-quiz/config 644
install_file files/etc/lab-inventory/config /etc/lab-inventory/config 644
install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755
install_file files/usr/local/lib/lab-quiz/lab-quiz-agent.py            /usr/local/lib/lab-quiz/lab-quiz-agent.py 755
install_file files/usr/local/lib/lab-inventory/lab-inventory-report    /usr/local/lib/lab-inventory/lab-inventory-report 755

systemctl restart lab-messages.service
systemctl restart lab-quiz.service
say "message servers: $(sed -n 's/^PRIMARY_SERVER=//p' /etc/lab-messages/config), then $(sed -n 's/^SERVER=//p' /etc/lab-messages/config)"
