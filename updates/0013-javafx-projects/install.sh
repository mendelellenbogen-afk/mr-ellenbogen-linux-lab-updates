#!/bin/bash
# 0013-javafx-projects
# IntelliJ's New Project > JavaFX wizard writes Java 8 into pom.xml, so new
# JavaFX projects fail with "modules are not supported in -source 8".
#  * lab-javafx-pom-fixer (a user service in every desktop session) changes
#    such pom.xml files to Java 25 within seconds; IntelliJ reloads them.
#    Only JavaFX Maven projects, each file once.
#  * New menu item "New JavaFX Project": copies the school's working starter
#    project into ~/IdeaProjects/<name> and opens it in IntelliJ.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

LIB=/usr/local/lib/lab-javafx
SHARE=/usr/local/share/lab-javafx

install_file files$LIB/javafx-pom-fixer.py   $LIB/javafx-pom-fixer.py 755
install_file files$LIB/new-javafx-project.py $LIB/new-javafx-project.py 755
install -d -o root -g root -m 755 $SHARE
rm -rf $SHARE/JavaFXStarter.new
cp -r files$SHARE/JavaFXStarter $SHARE/JavaFXStarter.new
chown -R root:root $SHARE/JavaFXStarter.new
chmod -R u=rwX,go=rX $SHARE/JavaFXStarter.new
chmod 755 $SHARE/JavaFXStarter.new/mvnw
rm -rf $SHARE/JavaFXStarter
mv $SHARE/JavaFXStarter.new $SHARE/JavaFXStarter
say "installed $SHARE/JavaFXStarter"

install_file files/usr/share/applications/lab-new-javafx-project.desktop /usr/share/applications/lab-new-javafx-project.desktop 644
install_file files/etc/systemd/user/lab-javafx-pom-fixer.service       /etc/systemd/user/lab-javafx-pom-fixer.service 644
systemctl --global enable lab-javafx-pom-fixer.service

# Start it now for everyone already logged in (others get it at their next login).
for user in $(loginctl list-sessions --no-legend | awk '$6 == "user" { print $3 }' | sort -u); do
    if [ "$(id -u "$user")" -ge 1000 ]; then
        systemctl --user -M "$user@" daemon-reload 2> /dev/null || true
        if systemctl --user -M "$user@" start lab-javafx-pom-fixer.service 2> /dev/null; then
            say "started the JavaFX fixer for $user"
        fi
    fi
done
say "done"
