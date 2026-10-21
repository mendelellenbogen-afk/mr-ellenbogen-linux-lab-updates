# 0033-remove-rustdesk

Teacher request, 2026-10-21: RustDesk is not needed on the lab laptops and does not work over TDSB Wi-Fi.

Removes what 0031-desktop-apps installed for RustDesk: stops and disables `rustdesk.service`, purges the
`rustdesk-unattended-wayland` (or `rustdesk`) package, deletes `/usr/local/bin/lab-rustdesk`,
`/usr/local/lib/lab-rustdesk`, the RustDesk desktop files and autostart entry, and each admin's
`~/.local/share/applications/rustdesk.desktop` (only if it carries 0031's marker line).

Not changed: Chrome, ChatGPT and Claude Desktop (also from 0031); RustDesk settings in users' home folders.
No restart needed. Safe to rerun.
