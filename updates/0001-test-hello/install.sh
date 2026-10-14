#!/bin/bash
# Harmless first test of the update pipeline: writes one small file, changes nothing else.
source "$LAB_UPDATER_HELPERS"

cat > /var/lib/lab-updater/hello-from-0001.txt <<NOTE
Update 0001-test-hello was installed on $(date -Iseconds).
If you can read this, remote updates work on this laptop.
NOTE
chmod 644 /var/lib/lab-updater/hello-from-0001.txt

say "wrote /var/lib/lab-updater/hello-from-0001.txt"
