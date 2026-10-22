#!/bin/bash
# 0037-microphone-unlock (2026-10-22). The teacher found "Dummy Output" (no
# sound at all) on lab-5cd137g4vb, an HP ProBook 650 G8. Cause: 0032's
# microphone lock. PipeWire only shows a sound card when it can open every
# device on it, so locking the capture devices hid the whole card, speakers
# and HDMI included, for every account. Confirmed on that laptop: opening the
# capture devices brought back every speaker/headphone/HDMI output.
# The teacher chose: get the sound back now, block microphones properly later.
#  * Cameras stay locked exactly as in 0032 (camera admin override kept).
#  * Microphones are no longer locked (sound capture devices and raw USB audio
#    devices get Ubuntu's normal permissions back).
#  * Re-applies the rules now, then restarts the sound service in every open
#    session, so sound returns without a reboot.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/etc/udev/rules.d/72-lab-capture.rules /etc/udev/rules.d/72-lab-capture.rules 644
install_file files/usr/local/sbin/lab-capture-policy /usr/local/sbin/lab-capture-policy 755
rm -f /etc/lab-capture/microphone-admin
# Ubuntu's normal permissions back on the sound devices 0032 locked (root:audio
# 0660); the refresh below then adds the logged-in user's access (uaccess).
for node in /dev/snd/pcmC*D*c /dev/snd/dsp* /dev/snd/adsp* /dev/snd/audio*; do
    if [ -c "$node" ]; then
        chown root:audio "$node" && chmod 0660 "$node" || say "could not reset $node (a reboot will)"
    fi
done
/usr/local/sbin/lab-capture-policy refresh

# Sound back in the sessions that are open now (a reboot also does it).
# loginctl columns: SESSION UID USER SEAT LEADER CLASS TTY IDLE SINCE
users=""
while read -r _session _uid user _seat _leader class _rest; do
    if [ "$class" = user ] && [[ " $users " != *" $user "* ]]; then
        users="$users $user"
    fi
done < <(loginctl list-sessions --no-legend 2>/dev/null || true)
for user in $users; do
    if systemctl --user --machine="$user@" restart wireplumber pipewire pipewire-pulse 2>/dev/null; then
        say "sound service restarted for $user"
    fi
done
say "microphones unlocked, cameras still locked (laptop $(hostname))"
