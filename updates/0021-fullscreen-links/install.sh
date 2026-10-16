#!/bin/bash
# 0021-fullscreen-links (the user's request, 2026-10-15)
# Live messages can open a link full screen with sound, set the volume, and
# close the full-screen window again:
#   tools/send-message --open "https://youtu.be/..." --fullscreen --volume 70
#   tools/send-message --close-fullscreen
# Full screen = a separate Firefox kiosk window with its own profile
# (~/snap/firefox/common/lab-fullscreen-profile) that may autoplay with sound;
# the student's own Firefox and settings are untouched. On YouTube a style
# rule in that profile stretches the video over the whole screen. Alt+F4
# closes it. A new full-screen link replaces the previous window.
# Volume = wpctl (PipeWire): unmute + set the percentage.
# All of it runs as the logged-in user via lab-present. Builds on 0019/0020.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-messages/lab-present              /usr/local/lib/lab-messages/lab-present 755
install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755

systemctl restart lab-messages.service
say "live messages: full-screen links, volume and close"
