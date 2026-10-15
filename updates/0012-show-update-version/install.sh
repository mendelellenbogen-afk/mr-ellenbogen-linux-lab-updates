#!/bin/bash
# 0012-show-update-version
# "Check for Lab Updates" now always shows which update the laptop is on,
# e.g. "This laptop is on update 0012 (show-update-version)", plus the channel
# when it isn't main (e.g. "testing channel"). Shows the next time it's opened.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-updater/check-for-updates.py /usr/local/lib/lab-updater/check-for-updates.py 755
