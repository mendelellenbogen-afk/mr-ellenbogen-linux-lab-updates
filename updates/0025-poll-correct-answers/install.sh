#!/bin/bash
# 0025-poll-correct-answers (the user's request, 2026-10-18)
# Class polls (0024) can now have correct answers: one or more, optional
# (without them a poll stays a plain opinion poll).
# * The correct answers are never sent with the poll, only with the results
#   when the teacher closes it ("poll_close" -> "correct": [option indexes]),
#   so no student can read them early from the poll file.
# * The results window then ticks the correct answers and tells each student
#   "Correct!" or "Not quite: the answer was C" on their own laptop.
# Laptops still on 0024 show the results without the verdict.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755
install_file files/usr/local/lib/lab-messages/poll-window.py           /usr/local/lib/lab-messages/poll-window.py 755

systemctl restart lab-messages.service
say "poll correct answers ready (laptop $(hostname))"
