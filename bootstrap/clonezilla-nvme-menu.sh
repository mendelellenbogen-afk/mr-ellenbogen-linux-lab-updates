#!/bin/bash
# Add a default "NVMe fix" entry to Clonezilla boot sticks' GRUB (UEFI) menu,
# so Dells with the Micron NVMe don't need the "e" edit at every boot.
#   bash clonezilla-nvme-menu.sh              every mounted Clonezilla boot stick
#   bash clonezilla-nvme-menu.sh MOUNTPOINT   just that one
# The new entry = the normal "Clonezilla live (VGA 800x600)" entry plus
#   nvme_core.default_ps_max_latency_us=0 pcie_aspm=off
# and is placed first, so it is the default. The original entries stay.
# Keeps boot/grub/grub.cfg.before-nvme-fix (first run only). Safe to re-run.
set -uo pipefail
OPTIONS="nvme_core.default_ps_max_latency_us=0 pcie_aspm=off"
TITLE="Clonezilla live (VGA 800x600, NVMe fix)"

fix_one() {
    local root="$1" cfg="$1/boot/grub/grub.cfg"
    echo "=== $root"
    if [ ! -f "$cfg" ] || ! grep -q 'menuentry "Clonezilla live (VGA 800x600)" --id live-default' "$cfg"; then
        echo "Not a Clonezilla boot stick (no standard grub.cfg). Skipped."; return 2
    fi
    if grep -q -- "--id live-nvme-fix" "$cfg"; then
        echo "Already has the NVMe fix entry. Nothing to do."; return 0
    fi
    [ -e "$cfg.before-nvme-fix" ] || cp -p "$cfg" "$cfg.before-nvme-fix" || return 1
    python3 - "$cfg" "$OPTIONS" "$TITLE" <<'PY' || return 1
import re, sys
path, options, title = sys.argv[1:]
text = open(path, encoding="utf-8").read()
match = re.search(r'menuentry "Clonezilla live \(VGA 800x600\)" --id live-default \{\n(.*?\n)\}\n', text, re.S)
body = match.group(1)
lines = body.split("\n")
for i, line in enumerate(lines):
    if line.strip().startswith("$linux_cmd "):
        lines[i] = line.rstrip() + " " + options
        break
else:
    sys.exit("no $linux_cmd line")
entry = f'menuentry "{title}" --id live-nvme-fix {{\n' + "\n".join(lines) + "}\n\n"
text = text[:match.start()] + entry + text[match.start():]
with open(path + ".new", "w", encoding="utf-8") as new:
    new.write(text)
PY
    mv "$cfg.new" "$cfg" && sync
    echo "Added \"$TITLE\" as the first (default) entry. Backup: boot/grub/grub.cfg.before-nvme-fix"
}

if [ $# -gt 0 ]; then
    fix_one "$1"; exit $?
fi
found=0
while read -r target; do
    case "$target" in /run/media/*|/media/*) ;; *) continue ;; esac
    [ -f "$target/boot/grub/grub.cfg" ] && [ -d "$target/live" ] || continue
    found=1
    fix_one "$target"
done < <(findmnt -rn -o TARGET)
[ "$found" = 1 ] || echo "No mounted Clonezilla boot stick found. Open it in Files first."
