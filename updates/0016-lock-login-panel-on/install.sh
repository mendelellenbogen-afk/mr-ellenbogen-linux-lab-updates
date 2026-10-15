#!/bin/bash
# 0016-lock-login-panel-on
# On some laptops the TDSB "Create Account" panel vanished from the login
# screen (and "Not listed?" came back). Cause, found on lab-b3psk13
# 2026-10-15: after a login-screen crash GNOME Shell saved
# disable-user-extensions in the greeter's own settings
# (/var/lib/gdm3/seat0/config/dconf/user), which switches off every add-on
# there, including ours, for good.
# Fix: the lab's GDM settings now set disable-user-extensions=false and LOCK
# it and enabled-extensions, so the greeter's own settings can't override
# them. Recompiles GDM's settings now; the panel returns the next time the
# login screen starts (log out, or restart). Safe to re-run.
source "$LAB_UPDATER_HELPERS"

install_file files/usr/share/gdm/dconf/99-school-account /usr/share/gdm/dconf/99-school-account 644
install_file files/usr/share/gdm/dconf/locks/99-school-account-locks /usr/share/gdm/dconf/locks/99-school-account-locks 644

if [ -x /usr/share/gdm/generate-config ] && /usr/share/gdm/generate-config; then
    say "login screen settings recompiled"
else
    say "could not recompile now; GDM does it at the next restart"
fi

if strings /var/lib/gdm3/seat0/config/dconf/user 2>/dev/null | grep -q disable-user-extensions; then
    say "this laptop had GNOME's 'extensions off' switch saved; it is now overridden"
fi
say "done (the panel shows the next time the login screen starts)"
