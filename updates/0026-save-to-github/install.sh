#!/bin/bash
# 0026-save-to-github (the user's goal, 2026-10-18)
# Students push their coding projects to GitHub from the lab laptops. They
# know nothing about GitHub, so it is one menu app with buttons:
#  * "Save to GitHub" (app menu): step-by-step sign-in (make a free account,
#    then a one-time code shown big with a Copy button), a list of the
#    student's projects (~/CS/..., ~/IdeaProjects, ~/PycharmProjects,
#    ~/GitHub and any other git project) with one button each, and
#    "Get a project from GitHub" for when they use a different laptop.
#  * The teacher's choices: students make their own accounts; new projects
#    are private; GitHub Classroom may come later (its repos are listed too).
#  * Installs the GitHub CLI (gh, Ubuntu package). After signing in, git in
#    VS Code / IntelliJ / PyCharm / the terminal can push too.
# Nothing is set up per account here: each student signs in from the app.
# Safe to re-run.
source "$LAB_UPDATER_HELPERS"

if ! command -v gh >/dev/null; then
    apt_install gh
fi
say "$(gh --version | head -1)"

install_file files/usr/local/lib/lab-github/save-to-github.py    /usr/local/lib/lab-github/save-to-github.py 755
install_file files/usr/local/share/applications/lab-save-to-github.desktop /usr/local/share/applications/lab-save-to-github.desktop 644
update-desktop-database -q /usr/local/share/applications 2>/dev/null || true
say "Save to GitHub is in the app menu"
