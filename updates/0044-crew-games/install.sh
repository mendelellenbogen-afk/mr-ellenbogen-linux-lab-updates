#!/bin/bash
# 0044-crew-games (2026-10-24; the class-games plan the teacher agreed on
# 2026-10-23, step 3: Cipher Heist)
# Class games in crews: the teacher's computer splits the class into crews at
# random (usually 6). Each laptop shows a big badge in its crew's colour and
# only that crew's locks, Clue Wall, hints and wrong guesses; every crew's
# openings show in the feed and the projector shows a crew scoreboard.
#  * A crew's wall posts arrive encrypted to that crew's laptops only (the
#    0023 envelope, like clue cards), so other crews can't read them.
#  * Cards meant for another crew are marked "Not yours", to be traded.
#  * A wrong guess freezes that crew's guessing for a while; the first crew
#    to open its vault wins, plays the ta-da everywhere and ends the game.
# Replaces 0043's game agent and window; escape rooms without crews work
# exactly as before. Needs 0043. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-game/lab-game-agent.py /usr/local/lib/lab-game/lab-game-agent.py 755
install_file files/usr/local/lib/lab-game/game-window.py    /usr/local/lib/lab-game/game-window.py 755

systemctl restart lab-game.service
say "crew games ready (laptop $(hostname))"
