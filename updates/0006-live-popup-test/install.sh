#!/bin/bash
# 0006-live-popup-test
# Installs a reusable tool for showing a message on every logged-in screen:
#     /usr/local/lib/lab-updater/show-message "Title" "Optional text"
# and uses it once to test live remote messages.
#
# Whoever is logged in when this update arrives sees the pop-up. A laptop that
# gets it later shows it to whoever is logged in then.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-updater/message-window.py /usr/local/lib/lab-updater/message-window.py 755
install_file files/usr/local/lib/lab-updater/show-message      /usr/local/lib/lab-updater/show-message 755

/usr/local/lib/lab-updater/show-message "Live Remote Update Test" \
    "This message was sent remotely to every lab laptop."
