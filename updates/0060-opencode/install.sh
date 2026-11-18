#!/bin/bash
# 0060-opencode (teacher's request 2026-11-18): OpenCode, the open-source AI
# coding agent, for the ICS3U culminating project (weeks 3-4; the teacher
# decides in class who may use it). Students start it by typing `opencode` in
# IntelliJ's Terminal tab inside their project folder.
#  * OpenCode 2.3.2 (newest stable, teacher's choice): the official Linux
#    binary from the GitHub release, checked against its published SHA-256,
#    installed root-owned in /usr/local/lib/opencode/2.3.2 (too big for this
#    repo, so it is downloaded here). Students can't change or update it.
#  * /usr/local/bin/opencode: wrapper (no ~/.claude files, no update checks,
#    private server that closes with OpenCode, refuses upgrade and --auto).
#  * /etc/opencode/opencode.json: machine-wide settings students can't
#    override: only OpenCode's own free models, and only those that don't use
#    data for training (teacher's choice; default Hy4 flash Free); no other
#    providers, logins or API keys (policies); sharing off; updates off;
#    edits, commands, web fetches and searches ask first; nothing outside the
#    folder OpenCode was started in.
#  * /usr/local/share/ics3u-cp/AGENTS.md: the teacher's rules template
#    (ICS3U-CP-AGENT-v1), and `ics3u-agents` to copy it into a project.
# Sessions stay in each student's home folder (~/.local/share/opencode);
# nothing is collected. No keys or secrets. Safe to rerun.
source "$LAB_UPDATER_HELPERS"

VERSION=2.3.2
URL="https://github.com/anomalyco/opencode/releases/download/v$VERSION/opencode-linux-x64.tar.gz"
SHA256=563b5d663637226b6e3bb4bb6803281bc39b0d2cd88db06d674b6420aab009b0
DIR=/usr/local/lib/opencode/$VERSION

if [ "$(uname -m)" != x86_64 ]; then
    say "OpenCode: this update is for x86_64 laptops only"
    exit 1
fi

if [ "$("$DIR/opencode" --version 2>/dev/null)" != "opencode v$VERSION" ]; then
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    say "downloading OpenCode $VERSION"
    wget -q --tries=3 --timeout=60 -O "$tmp/opencode.tar.gz" "$URL"
    echo "$SHA256  $tmp/opencode.tar.gz" | sha256sum -c --quiet -
    tar -xzf "$tmp/opencode.tar.gz" -C "$tmp" --no-same-owner opencode
    [ "$("$tmp/opencode" --version)" = "opencode v$VERSION" ]
    install -d -o root -g root -m 755 /usr/local/lib/opencode "$DIR"
    install -o root -g root -m 755 "$tmp/opencode" "$DIR/opencode.new"
    mv -f "$DIR/opencode.new" "$DIR/opencode"
fi

install -d -o root -g root -m 755 /etc/opencode /usr/local/share/ics3u-cp
install_file files/etc/opencode/opencode.json /etc/opencode/opencode.json 644
install_file files/usr/local/share/ics3u-cp/AGENTS.md /usr/local/share/ics3u-cp/AGENTS.md 644
install_file files/usr/local/bin/ics3u-agents /usr/local/bin/ics3u-agents 755
install_file files/usr/local/bin/opencode /usr/local/bin/opencode 755

[ "$(/usr/local/bin/opencode --version)" = "opencode v$VERSION" ]
say "done"
