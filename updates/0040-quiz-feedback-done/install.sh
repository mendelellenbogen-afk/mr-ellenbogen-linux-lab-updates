#!/bin/bash
# 0040-quiz-feedback-done (the teacher's request, 2026-10-23, during the first
# class with 0039: "We need to add a way for students to leave on their own
# when they are done looking at the feedback")
# Update 0039 kept a student who handed in a quiz with feedback in exam mode,
# looking at their marks, until the teacher ended the quiz. Now the marks page
# has "I'm done — close the quiz" (top right, and on the "Checking your
# answers" page); it asks once ("You can't open your marks again"), then the
# laptop ends exam mode for that student only and the window closes. Students
# still writing are not affected; the teacher's End works as before.
#  * lab-quiz agent and quiz window (0039's + "I'm done").
# A window that is open now keeps the 0039 version until it is opened again;
# answers are saved on disk. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/lib/lab-quiz/quiz-window.py    /usr/local/lib/lab-quiz/quiz-window.py 755
install_file files/usr/local/lib/lab-quiz/lab-quiz-agent.py /usr/local/lib/lab-quiz/lab-quiz-agent.py 755

systemctl restart lab-quiz.service
say "quiz feedback: students can close their marks when done"
