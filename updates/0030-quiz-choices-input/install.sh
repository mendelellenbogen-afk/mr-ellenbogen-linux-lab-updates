#!/bin/bash
# 0030-quiz-choices-input (for the teacher's Java Selection Test, 2026-10-19)
# Quiz window only (the quiz agent is unchanged):
#  * True/False and multiple-choice questions are answered with buttons.
#  * A question can show a code snippet with each part, a title such as
#    "Part A: True/False", and half marks (0.5).
#  * Run questions whose program reads the keyboard (Scanner) get an Input
#    box: what the student types there is the program's input.
# A quiz window that is open right now keeps the old version until it is
# closed; new quizzes open with this one. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-quiz/quiz-window.py /usr/local/lib/lab-quiz/quiz-window.py 755
say "quiz window updated: answer buttons and an Input box for Run"
