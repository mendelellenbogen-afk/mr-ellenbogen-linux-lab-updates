#!/bin/bash
# 0043-class-games (the teacher's request, 2026-10-23: "create a game for
# students to play among themselves between the laptops")
# Class games, starting with escape rooms: the teacher starts a game from
# their computer (tools/lab-game) and every student session gets the game
# window: the story, a shared timer, the locks, a Clue Wall everyone can
# post on, and a live feed. Each student gets a code name and their own clue
# cards; the class has to share them to open the locks.
#  * lab-game.service (root) listens on the game topic for events signed
#    with the lab key, keeps /run/lab-game/state.json, and opens the window.
#  * Clue cards come encrypted to this laptop's own message key; posts and
#    guesses go back signed with this laptop's key and encrypted to the
#    teacher's key. Answers are never on the laptop.
#  * Admin sessions get the big-screen view for the projector.
#  * "Class Game" in the app menu reopens the window while a game is on.
# Nothing happens until the teacher starts a game. Needs 0022/0023 (laptop
# keys, teacher key) and uses 0036's lab-sound when it is there. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

python3 -c "import cryptography" 2>/dev/null || apt_install python3-cryptography

install_file files/usr/local/lib/lab-game/lab-game-agent.py /usr/local/lib/lab-game/lab-game-agent.py 755
install_file files/usr/local/lib/lab-game/game-window.py    /usr/local/lib/lab-game/game-window.py 755
install_file files/etc/lab-game/config                      /etc/lab-game/config 644
install_file files/etc/systemd/system/lab-game.service      /etc/systemd/system/lab-game.service 644
install_file files/usr/local/share/applications/lab-game.desktop /usr/local/share/applications/lab-game.desktop 644

[ -f /var/lib/lab-inventory/laptop-key ] || systemctl start lab-inventory.service \
    || say "no laptop key yet: posts and guesses start working after the next inventory report"

systemctl daemon-reload
systemctl enable lab-game.service
systemctl restart lab-game.service
say "class games ready (laptop $(hostname)); idle until the teacher starts a game"
