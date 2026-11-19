#!/bin/bash
# 0061-opencode-tutor (teacher's request 2026-11-18): students also use
# OpenCode on ordinary ICS3U assignments, where it may only tutor (explain,
# hint, find bugs, review; never write or edit their code). Teacher's choice:
# a rules file copied into each project, not locked machine-wide rules.
#  * /usr/local/share/ics3u-cp/AGENTS-tutor.md: the tutor rules
#    (ICS3U-TUTOR-v1, drafted by Claude, approved by the teacher).
#  * /usr/local/bin/ics3u-agents: `ics3u-agents tutor` copies them into the
#    current folder as AGENTS.md; plain `ics3u-agents` still copies the
#    culminating project rules as before. Never overwrites an AGENTS.md.
# OpenCode itself and its lab settings (0060) are unchanged. Safe to rerun.
source "$LAB_UPDATER_HELPERS"

install -d -o root -g root -m 755 /usr/local/share/ics3u-cp
install_file files/usr/local/share/ics3u-cp/AGENTS-tutor.md /usr/local/share/ics3u-cp/AGENTS-tutor.md 644
install_file files/usr/local/bin/ics3u-agents /usr/local/bin/ics3u-agents 755
say "done"
