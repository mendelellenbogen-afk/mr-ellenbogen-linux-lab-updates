#!/bin/bash
# Rebuilds files/usr/local/lib/lab-snip/swappy (update 0058) on an Ubuntu 26.04
# computer: Swappy 1.5.1 (MIT licence, LICENSE-swappy) + the lab patch:
#   "+" button (closes the editor, starts a new snip after 0.5 s; command
#   SWAPPY_NEW_COMMAND, default /usr/local/bin/lab-snip), the picture copied
#   as soon as the editor opens, right-click copies it with the drawings.
# Not run on the laptops. Needs: git meson ninja-build gcc pkg-config
# libgtk-3-dev libcairo2-dev libpango1.0-dev libglib2.0-dev gettext.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git clone -q --depth 1 --branch v1.5.1 https://github.com/jtheoof/swappy.git "$work/src"
git -C "$work/src" apply "$here/0001-lab-new-button-autocopy-rightclick.patch"
meson setup "$work/build" "$work/src" --prefix=/usr/local -Dman-pages=disabled --buildtype=release >/dev/null
ninja -C "$work/build" >/dev/null
strip -o "$here/../files/usr/local/lib/lab-snip/swappy" "$work/build/swappy"
chmod 755 "$here/../files/usr/local/lib/lab-snip/swappy"
sha256sum "$here/../files/usr/local/lib/lab-snip/swappy"
