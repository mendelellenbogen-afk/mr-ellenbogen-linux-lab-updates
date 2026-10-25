#!/bin/bash
# 0046-carnival-crews (2026-10-25; the teacher's Grade 12 Data Management
# probability assignment, "The Rigged Carnival")
# Class games for marked class work: students wait in a lobby (the projector
# shows how many joined) until the teacher makes the crews (4s and 3s, as many
# 4s as possible); latecomers join the smallest crew.
#  * Fraction locks (5/18 or 0.278) and BONUS locks after the final lock.
#  * A crew that solves the case is placed (#1, #2...) and may leave; the game
#    goes on until the teacher ends it. The clock counts time played.
#  * After a lock opens, every student of the crew writes how the crew solved
#    it. That text goes signed and encrypted to the teacher only; the laptop
#    keeps it just in the student's own private file so the window can show it.
#  * Up to 12 crews; the projector shows a crew scoreboard with places and bonus stars.
# Replaces 0044's game agent and window; escape rooms (0043) and Cipher Heist
# (0044) work exactly as before. Needs 0043. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-game/lab-game-agent.py /usr/local/lib/lab-game/lab-game-agent.py 755
install_file files/usr/local/lib/lab-game/game-window.py    /usr/local/lib/lab-game/game-window.py 755

systemctl restart lab-game.service
say "carnival crews ready (laptop $(hostname))"
