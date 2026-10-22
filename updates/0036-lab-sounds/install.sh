#!/bin/bash
# 0036-lab-sounds (the teacher's request, 2026-10-22)
# Sounds on the lab laptops:
#  * lab-sound plays one of a fixed set of sounds in a desktop session:
#    tick, tada, applause (made from code by make-sounds.py; no recordings),
#    bell and ding (Ubuntu's own freedesktop sounds). New sounds come with a
#    new update.
#  * Live messages can play a sound: tools/send-message --sound NAME
#    [--volume N] on the teacher's computer, to every laptop, admins only, one
#    laptop or one student. A sound-only message shows no pop-up.
#  * Quizzes the teacher marks with sounds: the HAND IN countdown ticks and the
#    laptop cheers when the quiz is handed in. Real tests stay silent.
#  * The teacher can end a quiz with a countdown (tools/lab-quiz end SITTING
#    --countdown 10): a red bar shows the seconds left (ticking in quizzes with
#    sounds), then everyone's answers are handed in.
# A quiz window that is open right now keeps the old version until it is
# closed. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install -d -m 755 /usr/local/share/lab-sounds
for sound in files/usr/local/share/lab-sounds/*.wav; do
    install_file "$sound" "/usr/local/share/lab-sounds/$(basename "$sound")" 644
done
install_file files/usr/local/bin/lab-sound /usr/local/bin/lab-sound 755

install_file files/usr/local/lib/lab-messages/lab-messages-listener.py /usr/local/lib/lab-messages/lab-messages-listener.py 755
install_file files/usr/local/lib/lab-quiz/lab-quiz-agent.py /usr/local/lib/lab-quiz/lab-quiz-agent.py 755
install_file files/usr/local/lib/lab-quiz/quiz-window.py    /usr/local/lib/lab-quiz/quiz-window.py 755

systemctl restart lab-messages.service
systemctl restart lab-quiz.service
say "lab sounds ready: $(/usr/local/bin/lab-sound --list | tr '\n' ' ')"
