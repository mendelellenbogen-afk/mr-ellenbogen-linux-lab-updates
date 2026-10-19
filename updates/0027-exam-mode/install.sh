#!/bin/bash
# 0027-exam-mode (the teacher's goal and choices, 2026-10-18)
# Quizzes on the laptops: the teacher starts a quiz from their computer
# (tools/lab-quiz start); every targeted student session gets a full-screen
# quiz window with its own version (context, numbers, question order).
#  * Answers are saved every 3 s in the student's home folder; Hand in (or
#    the teacher's End) sends them signed with this laptop's inventory key and
#    encrypted to the teacher's key. A copy stays in /var/lib/lab-quiz.
#  * While a student is writing: internet blocked except the hand-in server
#    (nftables), other apps closed, USB storage/phones blocked, Alt+F2 off.
#    All of it is undone when they hand in or the teacher ends the quiz, and
#    whenever the service stops or starts with no quiz on.
#  * Run button only on the parts the teacher chose (java Main.java, 10 s).
# Nothing happens until the teacher starts a quiz. Needs 0022 (laptop key,
# teacher key). Safe to re-run.
source "$LAB_UPDATER_HELPERS"

command -v nft >/dev/null || apt_install nftables
python3 -c "import cryptography" 2>/dev/null || apt_install python3-cryptography

install_file files/usr/local/lib/lab-quiz/lab-quiz-agent.py /usr/local/lib/lab-quiz/lab-quiz-agent.py 755
install_file files/usr/local/lib/lab-quiz/quiz-window.py    /usr/local/lib/lab-quiz/quiz-window.py 755
install_file files/etc/lab-quiz/config                      /etc/lab-quiz/config 644
install_file files/etc/systemd/system/lab-quiz.service      /etc/systemd/system/lab-quiz.service 644
install -d -o root -g root -m 700 /var/lib/lab-quiz

[ -f /var/lib/lab-inventory/laptop-key ] || systemctl start lab-inventory.service \
    || say "no laptop key yet: hand-ins wait until the next inventory report makes one"

systemctl daemon-reload
systemctl enable lab-quiz.service
systemctl restart lab-quiz.service
say "exam mode ready (laptop $(hostname)); idle until the teacher starts a quiz"
