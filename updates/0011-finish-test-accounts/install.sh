#!/bin/bash
# 0011-finish-test-accounts
# Fixes 0010: its boot service / 15-minute timer stopped as soon as
# StudentTest2 was done, so a test account that was logged in when 0010
# arrived (e.g. teststudent) was never reset. Now they keep running until
# BOTH are done ($STATE_DIR/complete). Finishes the reset right away if the
# old account isn't logged in. Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/local/sbin/lab-reset-test-accounts              /usr/local/sbin/lab-reset-test-accounts 755
install_file files/etc/systemd/system/lab-reset-test-accounts.service  /etc/systemd/system/lab-reset-test-accounts.service 644
systemctl daemon-reload
systemctl enable lab-reset-test-accounts.service lab-reset-test-accounts.timer
systemctl restart lab-reset-test-accounts.timer

status=0
/usr/local/sbin/lab-reset-test-accounts || status=$?
case "$status" in
    0) say "both test accounts are ready (StudentTest1, StudentTest2)" ;;
    2) say "a test account is logged in; it will be reset after it logs out (or at the next restart)" ;;
    *) say "resetting the test accounts failed"; exit 1 ;;
esac
