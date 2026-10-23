#!/bin/bash
# 0039-quiz-feedback (the teacher's request, 2026-10-23: "update the practice
# quiz so it auto grades the results for students and shows them it right
# after submitting"; graded on the laptop; "after handing it in students would
# continue in the exam mode and get feedback directly overlayed over their
# quiz answers"; practice quiz only for now)
# For quizzes the teacher gives with feedback (FEEDBACK = True; the practice
# quiz), the quiz start brings a second file with the answer keys, encrypted
# to each lab laptop's own message key (from update 0023), so only the quiz
# agent (root) can open it. After a student hands in, the agent grades the
# answers on the laptop with the same grader as the teacher's computer
# (student code runs as nobody, without a network) and the quiz window shows
# the quiz again, locked, with the marks, what was wrong and the correct
# answer under each answer ("Your teacher marks this" on written answers).
# The student stays in exam mode until the teacher ends the quiz.
# Other quizzes, and laptops the key file isn't addressed to, work as before.
#  * lab-quiz agent (0038's + feedback), quiz window (0036's + the marks),
#    quizgrade.py (new: the grader).
# A quiz open right now carries on (answers are saved on disk; the window
# picks up the new version the next time it opens). Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-quiz/quizgrade.py      /usr/local/lib/lab-quiz/quizgrade.py 644
install_file files/usr/local/lib/lab-quiz/quiz-window.py    /usr/local/lib/lab-quiz/quiz-window.py 755
install_file files/usr/local/lib/lab-quiz/lab-quiz-agent.py /usr/local/lib/lab-quiz/lab-quiz-agent.py 755

systemctl restart lab-quiz.service
say "quiz feedback after hand-in installed"
