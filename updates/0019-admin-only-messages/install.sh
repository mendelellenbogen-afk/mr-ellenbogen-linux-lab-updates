#!/bin/bash
# 0019-admin-only-messages (the user's request, 2026-10-15)
# Lets the teacher send a live message only to admin sessions
# (tools/send-message --admins-only). Admin = sudo group, the same rule as
# 0017/0018 (only administrator today). Students and the StudentTest accounts
# never see these.
#  * The listener also subscribes to a second ntfy topic, ADMIN_TOPIC.
#    Laptops without this update don't listen there, so they never show an
#    admin message to a student.
#  * The signed payload says "to": "admins", so an admin message reposted to
#    the normal topic is still only shown to admins.
# Normal messages work exactly as before.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755
install_file files/etc/lab-messages/config                             /etc/lab-messages/config 644

systemctl restart lab-messages.service
say "live messages: listening for class and admin-only messages"
