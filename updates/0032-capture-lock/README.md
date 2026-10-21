# Built-in and USB capture lock

Release approved for main + testing, 2026-10-20. No passwords or remote enable endpoint.

By default V4L2 cameras/media nodes and ALSA capture PCM nodes are root-only.
The rules remove logind uaccess tags before the seat ACL rule, finalize owner,
group and permissions, and clear existing named-user ACLs after udev events.
USB devices advertising audio/video/still-image interfaces also have raw USB
access restricted to root to prevent bypass via libusb. This can affect raw-USB
camera/photo transfer and specialist audio software; normal speaker/headphone
ALSA playback nodes are unchanged. Legacy OSS audio nodes are blocked because
they combine recording and playback. Hotplug and reboot reapply the policy.

Bluetooth is deliberately unchanged, as requested: Bluetooth microphones still
work. This is an OS permission lock, not a physical hardware lock or a guarantee
against root, privileged capture brokers, other operating systems or untested
non-ALSA/non-V4L2 devices. Root/sudo administrators are trusted.

On an individual laptop, using an administrator terminal:

    lab-capture-policy status
    sudo lab-capture-policy camera admin
    sudo lab-capture-policy microphone admin
    sudo lab-capture-policy camera off
    sudo lab-capture-policy microphone off

Admin mode grants capture only to sudo-group accounts; students remain denied.
Camera and microphone overrides are independent and persist in root-owned
/etc/lab-capture. No marker means off. New sudo membership requires a fresh
login. Root-owned policy files cannot be edited by students. No sudoers grants.

Reboot after installation or changing to off: changing permissions does not
revoke previously opened device handles. Do not claim capture is fully stopped
until reboot. After enabling, reboot or log out/in so PipeWire rediscovers devices.
The update requests a reboot but does not force one or terminate a class.

Pilot on one laptop before a broad rollout: after reboot, test admin and student
browser camera/mic requests, direct ALSA/V4L2 access, USB headset/webcam hotplug,
normal speaker/headphone playback, independent admin overrides and relocking +
reboot. Confirm students remain denied even while an admin override is enabled.
Real hardware and root-running RustDesk capture behavior need checking; do not
assume these rules constrain privileged services. Bluetooth capture is allowed.

Implementation references: systemd udev permission/tag semantics
(https://www.freedesktop.org/software/systemd/man/latest/udev.html), and the
kernel ALSA device convention (`c` = capture, `p` = playback):
https://www.kernel.org/doc/html/latest/sound/alsa-configuration.html .
