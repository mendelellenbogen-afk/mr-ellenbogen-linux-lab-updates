# Lab desktop apps: RustDesk, Chrome, ChatGPT and Claude

Requested 2026-10-19. Installs the official **unattended Wayland preview**
1.5.0, enables its system service, and provides a menu launcher to members
of `sudo`. The service can share student sessions as well as admin sessions.
The menu restriction is not a security boundary around the vendor binary:
students can still run an installed executable directly and may see the
vendor service's tray UI. This does not add students to the sudo group.

The package replaces standard `rustdesk`. It is a preview: it worked on the
teacher's Hyprland desktop, but GNOME/mixed lab hardware, locked-screen and
reboot access require real-laptop validation. No reboot is requested.
The installer fails on unsupported architectures or a changed package hash.

## Package provenance

Bundled (about 24 MB) to avoid an unsigned or moving download during installation:

- Source: https://github.com/rustdesk/rustdesk/releases/tag/1.5.0
- Asset: `rustdesk-unattended-wayland-1.5.0-x86_64.deb`
- SHA-256: `9eed5e9f4b47af8ed41585c399cb2c0d2870e801c99645330dea1063ad844e09`
- Package: `rustdesk-unattended-wayland`, version `1.5.0`, architecture `amd64`.
- Preview documentation: https://rustdesk.com/blog/unattended-remote-access-wayland/

## Using it

Log in as an administrator and open **RustDesk**. Each laptop generates its
own ID and passwords; nothing is copied from another computer. Set a unique
permanent password privately in RustDesk if repeated unattended access is
needed. There is no shared fleet password or preauthorized remote controller.
Until configured, the app's own password/approval defaults apply; enabling
the service alone does not establish reliable unattended authentication.

The laptop must be awake and online. School Wi-Fi is forgotten at logout;
remote access does not bypass that policy or the exam-mode firewall. The
update does not disable sleep, alter the firewall, switch to X11, or change
RustDesk settings/secrets belonging to existing installations.

Global desktop overrides hide the normal launcher, and the lab launcher
checks `sudo` membership. An autostart helper reconciles the per-user menu
at login, including future admins and removal of the lab-created launcher
after sudo membership is removed. Existing admins get it immediately.

## Google Chrome Stable (all accounts)

Also requested 2026-10-19. Installs `google-chrome-stable` system-wide from
Google's HTTPS APT repository. Its vendor launcher appears for existing and
future administrator and student accounts. No student accounts/profiles are
created. No browser profiles or default-browser policies are deployed;
normal vendor browser registration applies.

The public Google signing key is bundled as `files/usr/share/keyrings/lab-google-chrome.gpg`;
the repository uses `signed-by` so the key is scoped to this source. Primary
fingerprint, checked against https://www.google.com/linuxrepositories/:
`EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796`.
APT authenticates repository metadata and package checksums. No Chrome binary
is bundled: the latest Stable package is downloaded on each laptop's first
installation, with future versions available through normal system updates.
Existing Chrome installations are kept; this update does not downgrade them.
The Google source file is `/etc/apt/sources.list.d/google-chrome.list`.

## ChatGPT and Claude Desktop (administrator accounts only)

Also requested 2026-10-19. Installs official `chatgpt` (Linux preview) and
`claude-desktop` (Linux beta) from their signed vendor APT repositories.
Existing installations are retained. Vendor public keys are bundled and
their fingerprints verified; an isolated APT update accepted all repository
signatures before release preparation.

- OpenAI: https://learn.chatgpt.com/docs/linux/linux-app
  - Repository: https://persistent.oaistatic.com/codex-app-prod/linux/deb
  - Key fingerprint: `3BFA0E4AE8B8CC16A2D9BA684A3B4A566C4660E4`, verified
    against the reviewed set in the official Linux Arch installer (26.1013.40934).
- Anthropic: https://support.claude.com/en/articles/10065433-install-claude-desktop
  - Repository: https://downloads.claude.ai/claude-desktop/apt/stable
  - Key fingerprint: `31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE`, verified
    against Anthropic's installation documentation.

Both vendor desktop entries are hidden globally and replaced with per-admin
launchers. A login helper handles future admins and removes lab-owned entries
after demotion. The checked launcher runs the app as the administrator user,
not as root. Additionally, `/usr/lib/chatgpt` and `/usr/lib/claude-desktop`
are set to `root:sudo`, mode `0750`, with dpkg-statoverride records so package
upgrades preserve the restrictions. Student accounts cannot traverse these
installed application directories, including via their normal binary paths.
An existing incompatible permission override aborts rather than being replaced.
This does not prevent students from using AI websites or installing a separate
copy in their own home folder.

Each admin signs in separately. No account login, token, project connection,
personal settings or chat history is copied from the teacher computer. These
apps occupy about 2.2 GB combined on the teacher computer (dependencies and
optional workspace images need more space). No Cowork workspace is downloaded
by this update, and no user is added to the kvm group. App-specific feature
requirements still apply. First launch/sign-in and the restrictions must be
confirmed on an actual lab laptop before relying on them in class.
