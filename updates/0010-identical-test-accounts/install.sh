#!/bin/bash
# 0010-identical-test-accounts
#  * The two test accounts become identical to each other and to a new TDSB
#    student account (they just don't need the TDSB-WIFI check):
#        teststudent -> studenttest1, shown as "StudentTest1"
#        studenttwo  -> studenttest2, shown as "StudentTest2"
#    Both are re-created with fresh home folders (their old files are deleted,
#    the user's decision), keep their passwords, get ~/CS/..., and are
#    protected from Delete My Account.
#  * Every student/staff account (test and TDSB, existing and new) joins the
#    "dialout" group, so the Arduino IDE can upload over USB (next login).
#
# A test account that is logged in right now is reset later (at boot, before
# the login screen, or within 15 minutes of logging out), so this update
# never waits on it. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

LIB=/usr/local/lib/school-account
SELF_DELETE=$LIB/self-delete

install_file files$LIB/create-student                   $LIB/create-student 755
install_file files/etc/school-account/keep-accounts      /etc/school-account/keep-accounts 644
install_file files$SELF_DELETE/self-delete-service.py    $SELF_DELETE/self-delete-service.py 755
install_file files$SELF_DELETE/self-delete-worker.py     $SELF_DELETE/self-delete-worker.py 755
rm -rf $SELF_DELETE/__pycache__
systemctl restart school-student-self-delete.service
systemctl restart school-student-self-delete-worker.service

install_file files/usr/local/sbin/lab-reset-test-accounts                 /usr/local/sbin/lab-reset-test-accounts 755
install_file files/etc/systemd/system/lab-reset-test-accounts.service     /etc/systemd/system/lab-reset-test-accounts.service 644
install_file files/etc/systemd/system/lab-reset-test-accounts.timer       /etc/systemd/system/lab-reset-test-accounts.timer 644
systemctl daemon-reload
systemctl enable lab-reset-test-accounts.service lab-reset-test-accounts.timer
systemctl start lab-reset-test-accounts.timer

status=0
/usr/local/sbin/lab-reset-test-accounts || status=$?
case "$status" in
    0) say "both test accounts are ready" ;;
    2) say "a test account is logged in; it will be reset after it logs out" ;;
    *) say "resetting the test accounts failed"; exit 1 ;;
esac
