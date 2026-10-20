#!/bin/bash
# 0031-desktop-apps (teacher requests, 2026-10-19).
# Install the official RustDesk 1.5.0 unattended Wayland preview that worked
# on the teacher's desktop. Enable its service for remote access, including
# student sessions; show the application-menu launcher only to sudo admins.
# Each laptop generates its own identity. No passwords/configuration copied.
# Also install Google Chrome Stable system-wide for every account, from
# Google's signed APT repository. No browser profiles or lab browser policies
# are deployed; normal vendor browser registration applies.
# Official ChatGPT (preview) and Claude Desktop (beta) are for sudo admins
# only: protect their application directories with persistent dpkg overrides.
# Safe to rerun after a partial installation; does not restart a running service.
source "$LAB_UPDATER_HELPERS"

if [ "$(dpkg --print-architecture)" != amd64 ]; then
    say "RustDesk preview and Google Chrome require amd64; refusing an incompatible installation"
    exit 1
fi
package=packages/rustdesk-unattended-wayland-1.5.0-x86_64.deb
echo "9eed5e9f4b47af8ed41585c399cb2c0d2870e801c99645330dea1063ad844e09  $package" | sha256sum -c -
installed="$(dpkg-query -W -f='${Status} ${Version}' rustdesk-unattended-wayland 2>/dev/null || true)"
install_file files/usr/share/keyrings/lab-google-chrome.gpg /usr/share/keyrings/lab-google-chrome.gpg 644
install_file files/etc/apt/sources.list.d/google-chrome.list /etc/apt/sources.list.d/google-chrome.list 644
install_file files/usr/share/keyrings/chatgpt-archive-keyring.gpg /usr/share/keyrings/chatgpt-archive-keyring.gpg 644
install_file files/usr/share/keyrings/claude-desktop-archive-keyring.asc /usr/share/keyrings/claude-desktop-archive-keyring.asc 644
install_file files/etc/apt/sources.list.d/chatgpt.sources /etc/apt/sources.list.d/chatgpt.sources 644
install_file files/etc/apt/sources.list.d/claude-desktop.list /etc/apt/sources.list.d/claude-desktop.list 644

# Register restrictions before unpacking so a fresh install is restricted
# immediately, and future dpkg upgrades preserve the directory permissions.
for dir in /usr/lib/chatgpt /usr/lib/claude-desktop; do
    override="$(dpkg-statoverride --list "$dir" || true)"
    if [ -z "$override" ]; then
        dpkg-statoverride --add root sudo 0750 "$dir"
    elif [ "$override" != "root sudo 750 $dir" ] && [ "$override" != "root sudo 0750 $dir" ]; then
        say "conflicting permission override for $dir; refusing to overwrite it"
        exit 1
    fi
done
packages=()
if [ "$installed" != 'install ok installed 1.5.0' ]; then
    packages+=("$PWD/$package")
fi
chrome_installed="$(dpkg-query -W -f='${Status}' google-chrome-stable 2>/dev/null || true)"
if [ "$chrome_installed" != 'install ok installed' ]; then
    packages+=(google-chrome-stable)
fi
for app in chatgpt claude-desktop; do
    if [ "$(dpkg-query -W -f='${Status}' "$app" 2>/dev/null || true)" != 'install ok installed' ]; then
        packages+=("$app")
    fi
done
[ "${#packages[@]}" -eq 0 ] || apt_install "${packages[@]}"
for dir in /usr/lib/chatgpt /usr/lib/claude-desktop; do
    chown root:sudo "$dir"
    chmod 0750 "$dir"
done

install_file files/usr/local/bin/lab-rustdesk /usr/local/bin/lab-rustdesk 755
install_file files/usr/local/lib/lab-rustdesk/admin-menu /usr/local/lib/lab-rustdesk/admin-menu 755
install_file files/usr/local/lib/lab-rustdesk/rustdesk.desktop /usr/local/lib/lab-rustdesk/rustdesk.desktop 644
install_file files/usr/local/share/applications/rustdesk.desktop /usr/local/share/applications/rustdesk.desktop 644
install_file files/usr/local/share/applications/rustdesk-link.desktop /usr/local/share/applications/rustdesk-link.desktop 644
install_file files/etc/xdg/autostart/lab-rustdesk-menu.desktop /etc/xdg/autostart/lab-rustdesk-menu.desktop 644
install_file files/usr/local/bin/lab-ai-desktop /usr/local/bin/lab-ai-desktop 755
install_file files/usr/local/lib/lab-ai-desktop/admin-menu /usr/local/lib/lab-ai-desktop/admin-menu 755
install_file files/usr/local/lib/lab-ai-desktop/chatgpt.desktop /usr/local/lib/lab-ai-desktop/chatgpt.desktop 644
install_file files/usr/local/lib/lab-ai-desktop/com.anthropic.Claude.desktop /usr/local/lib/lab-ai-desktop/com.anthropic.Claude.desktop 644
install_file files/usr/local/share/applications/chatgpt.desktop /usr/local/share/applications/chatgpt.desktop 644
install_file files/usr/local/share/applications/com.anthropic.Claude.desktop /usr/local/share/applications/com.anthropic.Claude.desktop 644
install_file files/etc/xdg/autostart/lab-ai-desktop-menu.desktop /etc/xdg/autostart/lab-ai-desktop-menu.desktop 644

# Populate existing admins now. Autostart reconciles the menu for future
# accounts/group changes at login, without writing into homes as root.
while IFS=: read -r user _ uid _ _ home _; do
    [ "$uid" -ge 1000 ] && [ -d "$home" ] || continue
    if id -nG "$user" | tr ' ' '\n' | grep -qx sudo; then
        runuser -u "$user" -- /usr/local/lib/lab-rustdesk/admin-menu
        runuser -u "$user" -- /usr/local/lib/lab-ai-desktop/admin-menu
    fi
done < <(getent passwd)

systemctl daemon-reload
systemctl enable --now rustdesk.service
say "RustDesk ready: admin menu entry; unattended service enabled"
say "Set permanent passwords privately on each laptop; none were deployed"
say "Google Chrome Stable available to all accounts; Google APT repository configured"
say "ChatGPT and Claude Desktop installed for sudo admins only; sign in separately"
