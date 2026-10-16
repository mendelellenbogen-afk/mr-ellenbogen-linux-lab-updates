#!/bin/bash
# 0020-open-links (the user's request, 2026-10-15)
# Live messages can open a web page: tools/send-message --open "https://..."
# opens the link in the default browser of every logged-in desktop (or only
# admin desktops with --admins-only). Only plain http/https links are opened;
# anything else is ignored. With no text, there is no pop-up; if the browser
# can't be started for a user, that user gets the pop-up with the link instead.
# Laptops without this update show a pop-up with the link in the Copy box.
# Builds on 0019 (admin-only messages); the config is unchanged.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755

systemctl restart lab-messages.service
say "live messages: can now open web links"
