#!/bin/bash
# 0023-targeted-messages (the user's request, 2026-10-16)
# Send live messages (pop-ups, links, full screen, volume) to particular
# laptops by name, or to particular students by ID:
#   tools/send-message --laptop lab-jq8fzm2 --text "..."
#   tools/send-message --student 349681030 --text "..."
# * The inventory reporter now also makes this laptop's own message key
#   (X25519; /var/lib/lab-inventory/message-key, root only, remade when the
#   machine-id changes) and reports its public half to the teacher.
# * The listener also listens on TARGET_TOPIC. A targeted message is
#   encrypted to each target laptop's key; inside is a normal lab-signed
#   message naming the laptops ("to_laptops") and optionally the students
#   ("to_students": only their sessions see it). Student IDs never travel in
#   the clear. Laptops without 0023 don't listen there.
# * /usr/local/lib/lab-updater/targeting.sh: only_on_laptops and
#   student_accounts, for updates meant for some laptops or students.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-inventory/lab-inventory-report   /usr/local/lib/lab-inventory/lab-inventory-report 755
install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755
install_file files/etc/lab-messages/config                            /etc/lab-messages/config 644
install_file files/usr/local/lib/lab-updater/targeting.sh             /usr/local/lib/lab-updater/targeting.sh 644

install -d -m 700 /var/lib/lab-inventory
# Make the message key and report it now (the report changed, so it is sent
# right away if someone is logged in), then restart the listener.
systemctl start lab-inventory.service || say "inventory report will retry in 5 minutes"
systemctl restart lab-messages.service
say "targeted messages ready (laptop $(hostname))"
